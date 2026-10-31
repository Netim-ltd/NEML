# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Database-backed model rollout with real approval rows and robot acknowledgements."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import sqlalchemy as sa
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from sqlalchemy.ext.asyncio import AsyncSession

from neml_brain.platform.core import Scope
from neml_brain.platform.edge import DeploymentTicket, ModelAck, TicketRequest, sign_ticket
from neml_brain.platform.learning import (
    AcceptanceThresholds,
    CandidateMetrics,
    Deployment,
    Stage,
)
from neml_brain.platform.robots import ModelRegistry
from neml_brain.platform.store import PlatformStore


class DeploymentManager:
    def __init__(
        self,
        store: PlatformStore,
        thresholds: AcceptanceThresholds,
        signer: ModelRegistry,
        max_canary_robots: int = 1,
    ) -> None:
        if max_canary_robots < 1:
            raise ValueError("canary must permit at least one robot")
        self.store = store
        self.thresholds = thresholds
        self.signer = signer
        self.max_canary_robots = max_canary_robots

    async def monitor_all_canaries(self) -> None:
        """Periodic safety sweep; only requests rollback, never automatic fleet rollout."""
        async with self.store._sessions() as session:
            tenant_ids = cast(
                list[str],
                (
                    (await session.execute(sa.text("SELECT id FROM platform_tenants ORDER BY id")))
                    .scalars()
                    .all()
                ),
            )
        for tenant_id in tenant_ids:
            index_scope = Scope(tenant_id, "_index")
            async with self.store._scoped(index_scope) as session:
                domain_ids = cast(
                    list[str],
                    (
                        (
                            await session.execute(
                                sa.text("""
                            SELECT id FROM platform_domains
                            WHERE tenant_id = :tenant ORDER BY id
                        """),
                                {"tenant": tenant_id},
                            )
                        )
                        .scalars()
                        .all()
                    ),
                )
            for domain_id in domain_ids:
                scope = Scope(tenant_id, domain_id)
                async with self.store._scoped(scope) as session:
                    candidates = (
                        await session.execute(
                            sa.text("""
                                SELECT robot_type, candidate_version
                                FROM platform_deployments
                                WHERE tenant_id = :tenant AND domain_id = :domain
                                  AND stage = 'canary'
                            """),
                            {"tenant": tenant_id, "domain": domain_id},
                        )
                    ).all()
                for robot_type, candidate_version in candidates:
                    try:
                        await self.request_transition(scope, robot_type, candidate_version)
                    except PermissionError:
                        # Good/insufficient canary data still needs operator
                        # approval for fleet; only a failing canary rolls back.
                        continue

    async def request_human_approval(
        self, scope: Scope, robot_type: str, candidate_version: str, target: str
    ) -> str:
        """Create a scoped level-3 approval and durable cloud notification."""
        if target not in ("canary", "fleet"):
            raise ValueError("approval target must be canary or fleet")
        subject = f"{robot_type}:{candidate_version}:{target}"
        expected_stage = Stage.SIM_VALIDATED if target == "canary" else Stage.CANARY
        async with self.store._scoped(scope) as session:
            stage = (
                await session.execute(
                    sa.text("""
                        SELECT stage FROM platform_deployments
                        WHERE tenant_id = :tenant AND domain_id = :domain
                          AND robot_type = :type AND candidate_version = :version
                    """),
                    {
                        "tenant": scope.tenant_id,
                        "domain": scope.domain_id,
                        "type": robot_type,
                        "version": candidate_version,
                    },
                )
            ).scalar_one_or_none()
            if stage != expected_stage.value:
                raise PermissionError("deployment is not ready for this approval")
            prior = (
                await session.execute(
                    sa.text("""
                        SELECT id FROM approvals
                        WHERE subject_kind = 'model_deployment' AND subject_id = :subject
                          AND payload->>'tenant_id' = :tenant
                          AND payload->>'domain_id' = :domain
                          AND decision IS NULL AND expires_at > now()
                        ORDER BY requested_at DESC LIMIT 1
                    """),
                    {
                        "subject": subject,
                        "tenant": scope.tenant_id,
                        "domain": scope.domain_id,
                    },
                )
            ).scalar_one_or_none()
            if prior is not None:
                return str(prior)
            expires = datetime.now(UTC) + timedelta(hours=24)
            request_payload = {
                "tenant_id": scope.tenant_id,
                "domain_id": scope.domain_id,
                "robot_type": robot_type,
                "model_version": candidate_version,
                "target": target,
            }
            approval_id = (
                await session.execute(
                    sa.text("""
                        INSERT INTO approvals
                          (level, subject_kind, subject_id, payload, expires_at)
                        VALUES (3, 'model_deployment', :subject,
                                CAST(:payload AS jsonb), :expires)
                        RETURNING id
                    """),
                    {
                        "subject": subject,
                        "payload": json.dumps(request_payload),
                        "expires": expires,
                    },
                )
            ).scalar_one()
            cloud_request = {
                "approvalId": str(approval_id),
                "level": 3,
                "subjectKind": "model_deployment",
                "subjectId": subject,
                "expiresAt": expires.isoformat(),
                "payload": request_payload,
            }
            event_id = str(uuid4())
            await session.execute(
                sa.text("""
                    INSERT INTO platform_events
                      (tenant_id, domain_id, id, kind, subject_id, schema_version,
                       occurred_at, payload)
                    VALUES (:tenant, :domain, :id, 'ApprovalRequested', :subject,
                            1, now(), CAST(:payload AS jsonb))
                """),
                {
                    "tenant": scope.tenant_id,
                    "domain": scope.domain_id,
                    "id": event_id,
                    "subject": subject,
                    "payload": json.dumps(request_payload),
                },
            )
            await session.execute(
                sa.text("""
                    INSERT INTO platform_outbox (tenant_id, domain_id, event_id, payload)
                    VALUES (:tenant, :domain, :id, CAST(:payload AS jsonb))
                """),
                {
                    "tenant": scope.tenant_id,
                    "domain": scope.domain_id,
                    "id": event_id,
                    "payload": json.dumps(
                        {"kind": "ApprovalRequested", "cloud_request": cloud_request}
                    ),
                },
            )
            return str(approval_id)

    async def issue_ticket(
        self, scope: Scope, robot_id: str, robot_type: str, candidate_version: str
    ) -> DeploymentTicket:
        """Sign only a database-pending transition already through its approval gate."""
        async with self.store._scoped(scope) as session:
            robot_exists = (
                await session.execute(
                    sa.text("""
                        SELECT 1 FROM platform_units
                        WHERE tenant_id = :tenant AND domain_id = :domain
                          AND id = :robot AND rank = 3 AND robot_type = :type
                    """),
                    {
                        "tenant": scope.tenant_id,
                        "domain": scope.domain_id,
                        "robot": robot_id,
                        "type": robot_type,
                    },
                )
            ).scalar_one_or_none()
            if robot_exists is None:
                raise PermissionError("robot is not registered in this tenant/domain/type")
            row = (
                await session.execute(
                    sa.text("""
                        SELECT previous_version, stage, canary_approval_id, fleet_approval_id
                        FROM platform_deployments
                        WHERE tenant_id = :tenant AND domain_id = :domain
                          AND robot_type = :type AND candidate_version = :version
                        FOR UPDATE
                    """),
                    {
                        "tenant": scope.tenant_id,
                        "domain": scope.domain_id,
                        "type": robot_type,
                        "version": candidate_version,
                    },
                )
            ).one_or_none()
            if row is None:
                raise KeyError("deployment does not exist")
            stage = Stage(row.stage)
            if stage is Stage.CANARY_PENDING:
                approval_id = str(row.canary_approval_id) if row.canary_approval_id else None
                version, target = candidate_version, "canary"
            elif stage is Stage.FLEET_PENDING:
                approval_id = str(row.fleet_approval_id) if row.fleet_approval_id else None
                version, target = candidate_version, "fleet"
            elif stage is Stage.ROLLBACK_PENDING:
                approval_id = None
                version, target = row.previous_version, "rollback"
                was_deployed = (
                    await session.execute(
                        sa.text("""
                            SELECT 1 FROM platform_deployment_targets
                            WHERE tenant_id = :tenant AND domain_id = :domain
                              AND robot_type = :type AND candidate_version = :version
                              AND robot_id = :robot AND stage IN ('canary', 'fleet')
                              AND acknowledged_at IS NOT NULL
                            LIMIT 1
                        """),
                        {
                            "tenant": scope.tenant_id,
                            "domain": scope.domain_id,
                            "type": robot_type,
                            "version": candidate_version,
                            "robot": robot_id,
                        },
                    )
                ).scalar_one_or_none()
                if was_deployed is None:
                    raise PermissionError("robot never applied the candidate model")
            else:
                raise PermissionError("no physical deployment is pending")
            if target != "rollback" and approval_id is None:
                raise PermissionError("missing human approval on pending deployment")
            if target == "canary":
                existing = (
                    await session.execute(
                        sa.text("""
                            SELECT count(DISTINCT robot_id) FROM platform_deployment_targets
                            WHERE tenant_id = :tenant AND domain_id = :domain
                              AND robot_type = :type AND candidate_version = :version
                              AND stage = 'canary'
                        """),
                        {
                            "tenant": scope.tenant_id,
                            "domain": scope.domain_id,
                            "type": robot_type,
                            "version": candidate_version,
                        },
                    )
                ).scalar_one()
                already_targeted = (
                    await session.execute(
                        sa.text("""
                            SELECT 1 FROM platform_deployment_targets
                            WHERE tenant_id = :tenant AND domain_id = :domain
                              AND robot_type = :type AND candidate_version = :version
                              AND robot_id = :robot AND stage = 'canary'
                        """),
                        {
                            "tenant": scope.tenant_id,
                            "domain": scope.domain_id,
                            "type": robot_type,
                            "version": candidate_version,
                            "robot": robot_id,
                        },
                    )
                ).scalar_one_or_none()
                if not already_targeted and existing >= self.max_canary_robots:
                    raise PermissionError("canary robot limit reached")
            await session.execute(
                sa.text("""
                    INSERT INTO platform_deployment_targets
                      (tenant_id, domain_id, robot_type, candidate_version, robot_id, stage)
                    VALUES (:tenant, :domain, :type, :version, :robot, :stage)
                    ON CONFLICT DO NOTHING
                """),
                {
                    "tenant": scope.tenant_id,
                    "domain": scope.domain_id,
                    "type": robot_type,
                    "version": candidate_version,
                    "robot": robot_id,
                    "stage": target,
                },
            )
            unsigned = DeploymentTicket(
                scope,
                robot_id,
                robot_type,
                version,
                target,
                approval_id,
                datetime.now(UTC) + timedelta(minutes=5),
                "",
                candidate_version,
            )
            return sign_ticket(unsigned, self.signer._private)

    async def request_ticket_signed(self, request: TicketRequest) -> DeploymentTicket | None:
        if abs((datetime.now(UTC) - request.occurred_at).total_seconds()) > 300:
            raise PermissionError("ticket request is stale")
        if len(request.nonce) != 32:
            raise PermissionError("ticket request nonce is invalid")
        async with self.store._scoped(request.scope) as session:
            public_key = (
                await session.execute(
                    sa.text("""
                        SELECT device_public_key FROM platform_units
                        WHERE tenant_id = :tenant AND domain_id = :domain
                          AND id = :robot AND robot_type = :type AND rank = 3
                    """),
                    {
                        "tenant": request.scope.tenant_id,
                        "domain": request.scope.domain_id,
                        "robot": request.robot_id,
                        "type": request.robot_type,
                    },
                )
            ).scalar_one_or_none()
            if public_key is None:
                raise PermissionError("robot device key is not registered")
            try:
                Ed25519PublicKey.from_public_bytes(public_key).verify(
                    bytes.fromhex(request.signature), request.signed_bytes()
                )
            except (InvalidSignature, ValueError) as exc:
                raise PermissionError("ticket request signature invalid") from exc
            candidates = (
                await session.execute(
                    sa.text("""
                        SELECT candidate_version, stage FROM platform_deployments
                        WHERE tenant_id = :tenant AND domain_id = :domain
                          AND robot_type = :type
                          AND stage IN ('rollback_pending', 'canary_pending', 'fleet_pending')
                        ORDER BY CASE stage
                          WHEN 'rollback_pending' THEN 0
                          WHEN 'canary_pending' THEN 1 ELSE 2 END,
                          updated_at
                    """),
                    {
                        "tenant": request.scope.tenant_id,
                        "domain": request.scope.domain_id,
                        "type": request.robot_type,
                    },
                )
            ).all()
        for version, _stage in candidates:
            try:
                return await self.issue_ticket(
                    request.scope, request.robot_id, request.robot_type, version
                )
            except PermissionError:
                continue
        return None

    async def verify_ticket(self, ticket: DeploymentTicket) -> None:
        if ticket.expires_at <= datetime.now(UTC):
            raise PermissionError("deployment ticket expired")
        try:
            self.signer.public_key.verify(bytes.fromhex(ticket.signature), ticket.signed_bytes())
        except (InvalidSignature, ValueError) as exc:
            raise PermissionError("deployment ticket signature invalid") from exc
        if ticket.stage not in ("canary", "fleet", "rollback"):
            raise PermissionError("invalid ticket stage")
        pending = {
            "canary": Stage.CANARY_PENDING.value,
            "fleet": Stage.FLEET_PENDING.value,
            "rollback": Stage.ROLLBACK_PENDING.value,
        }[ticket.stage]
        async with self.store._scoped(ticket.scope) as session:
            row = (
                await session.execute(
                    sa.text("""
                        SELECT d.candidate_version, d.previous_version,
                               d.canary_approval_id, d.fleet_approval_id
                        FROM platform_deployments d
                        JOIN platform_deployment_targets t
                          ON t.tenant_id = d.tenant_id AND t.domain_id = d.domain_id
                         AND t.robot_type = d.robot_type
                         AND t.candidate_version = d.candidate_version
                        WHERE d.tenant_id = :tenant AND d.domain_id = :domain
                          AND d.robot_type = :type AND d.stage = :pending
                          AND t.robot_id = :robot AND t.stage = :target
                        LIMIT 1
                    """),
                    {
                        "tenant": ticket.scope.tenant_id,
                        "domain": ticket.scope.domain_id,
                        "type": ticket.robot_type,
                        "pending": pending,
                        "robot": ticket.robot_id,
                        "target": ticket.stage,
                    },
                )
            ).one_or_none()
            if row is None:
                raise PermissionError("ticket target is no longer pending")
            expected_version = (
                row.previous_version if ticket.stage == "rollback" else row.candidate_version
            )
            expected_approval = (
                None
                if ticket.stage == "rollback"
                else str(
                    row.canary_approval_id if ticket.stage == "canary" else row.fleet_approval_id
                )
            )
            if (
                ticket.version != expected_version
                or ticket.candidate_version != row.candidate_version
                or ticket.approval_id != expected_approval
            ):
                raise PermissionError("ticket no longer matches the approved rollout")

    async def request_transition(
        self,
        scope: Scope,
        robot_type: str,
        candidate_version: str,
        *,
        metrics: CandidateMetrics | None = None,
        approval_id: str | None = None,
    ) -> Deployment:
        async with self.store._scoped(scope) as session:
            row = (
                await session.execute(
                    sa.text("""
                        SELECT previous_version, stage FROM platform_deployments
                        WHERE tenant_id = :tenant AND domain_id = :domain
                          AND robot_type = :type AND candidate_version = :version
                        FOR UPDATE
                    """),
                    {
                        "tenant": scope.tenant_id,
                        "domain": scope.domain_id,
                        "type": robot_type,
                        "version": candidate_version,
                    },
                )
            ).one_or_none()
            if row is None:
                raise KeyError("deployment does not exist in this tenant/domain")
            current = Deployment(
                scope, robot_type, candidate_version, row.previous_version, Stage(row.stage)
            )
            canary_failure_rate = None
            if current.stage is Stage.CANARY:
                counts = (
                    await session.execute(
                        sa.text("""
                            SELECT count(*) AS total,
                                   count(*) FILTER (WHERE e.outcome <> 'success') AS failed
                            FROM platform_episodes e
                            JOIN platform_deployment_targets t
                              ON t.tenant_id = e.tenant_id AND t.domain_id = e.domain_id
                             AND t.robot_id = e.robot_id AND t.robot_type = e.robot_type
                             AND t.candidate_version = e.model_version
                            WHERE e.tenant_id = :tenant AND e.domain_id = :domain
                              AND e.robot_type = :type AND e.model_version = :version
                              AND e.quality >= 0.8 AND t.stage = 'canary'
                              AND t.acknowledged_at IS NOT NULL
                              AND e.observed_at >= t.acknowledged_at
                        """),
                        {
                            "tenant": scope.tenant_id,
                            "domain": scope.domain_id,
                            "type": robot_type,
                            "version": candidate_version,
                        },
                    )
                ).one()
                if counts.total < 20:
                    raise PermissionError("canary needs at least 20 verified episodes")
                canary_failure_rate = counts.failed / counts.total
            if current.stage in (Stage.SIM_VALIDATED, Stage.CANARY) and not (
                current.stage is Stage.CANARY
                and canary_failure_rate is not None
                and canary_failure_rate > self.thresholds.max_canary_failure
            ):
                if approval_id is None:
                    raise PermissionError("physical model rollout needs a human approval")
                try:
                    UUID(approval_id)
                except ValueError as exc:
                    raise PermissionError("invalid approval ID") from exc
                target = "canary" if current.stage is Stage.SIM_VALIDATED else "fleet"
                subject = f"{robot_type}:{candidate_version}:{target}"
                approved = (
                    await session.execute(
                        sa.text("""
                            SELECT 1 FROM approvals
                            WHERE id = CAST(:id AS uuid)
                              AND subject_kind = 'model_deployment'
                              AND subject_id = :subject
                              AND payload->>'tenant_id' = :tenant
                              AND payload->>'domain_id' = :domain
                              AND decision = 'approved' AND decided_by IS NOT NULL
                              AND expires_at > now() AND level >= 3
                        """),
                        {
                            "id": approval_id,
                            "subject": subject,
                            "tenant": scope.tenant_id,
                            "domain": scope.domain_id,
                        },
                    )
                ).scalar_one_or_none()
                if approved is None:
                    raise PermissionError("scoped human approval was not verified")
            updated = current.advance(
                metrics=metrics,
                thresholds=self.thresholds,
                human_approval_id=approval_id,
                canary_failure_rate=canary_failure_rate,
            )
            await self._write_transition(session, updated, approval_id)
            return updated

    async def acknowledge(
        self,
        scope: Scope,
        robot_id: str,
        robot_type: str,
        candidate_version: str,
        applied_version: str,
        claimed_stage: str,
    ) -> Deployment:
        """Call only after a device-authenticated bridge acknowledgement."""
        async with self.store._scoped(scope) as session:
            row = (
                await session.execute(
                    sa.text("""
                        SELECT previous_version, stage FROM platform_deployments
                        WHERE tenant_id = :tenant AND domain_id = :domain
                          AND robot_type = :type AND candidate_version = :version
                        FOR UPDATE
                    """),
                    {
                        "tenant": scope.tenant_id,
                        "domain": scope.domain_id,
                        "type": robot_type,
                        "version": candidate_version,
                    },
                )
            ).one_or_none()
            if row is None:
                raise KeyError("deployment does not exist")
            current = Deployment(
                scope, robot_type, candidate_version, row.previous_version, Stage(row.stage)
            )
            updated = current.acknowledge(applied_version)
            stage_label = {
                Stage.CANARY_PENDING: "canary",
                Stage.FLEET_PENDING: "fleet",
                Stage.ROLLBACK_PENDING: "rollback",
            }[current.stage]
            if claimed_stage != stage_label:
                raise PermissionError("robot acknowledgement stage mismatch")
            result = await session.execute(
                sa.text("""
                    UPDATE platform_deployment_targets
                    SET acknowledged_at = now(), applied_version = :applied
                    WHERE tenant_id = :tenant AND domain_id = :domain
                      AND robot_type = :type AND candidate_version = :version
                      AND robot_id = :robot AND stage = :stage
                    RETURNING robot_id
                """),
                {
                    "tenant": scope.tenant_id,
                    "domain": scope.domain_id,
                    "type": robot_type,
                    "version": candidate_version,
                    "robot": robot_id,
                    "stage": stage_label,
                    "applied": applied_version,
                },
            )
            if result.scalar_one_or_none() is None:
                raise PermissionError("robot was not a target of this rollout")
            counts = (
                await session.execute(
                    sa.text("""
                        SELECT count(*) AS total, count(acknowledged_at) AS done
                        FROM platform_deployment_targets
                        WHERE tenant_id = :tenant AND domain_id = :domain
                          AND robot_type = :type AND candidate_version = :version
                          AND stage = :stage
                    """),
                    {
                        "tenant": scope.tenant_id,
                        "domain": scope.domain_id,
                        "type": robot_type,
                        "version": candidate_version,
                        "stage": stage_label,
                    },
                )
            ).one()
            if stage_label == "fleet":
                required: int = (
                    await session.execute(
                        sa.text("""
                            SELECT count(*) FROM platform_units
                            WHERE tenant_id = :tenant AND domain_id = :domain
                              AND rank = 3 AND robot_type = :type
                        """),
                        {
                            "tenant": scope.tenant_id,
                            "domain": scope.domain_id,
                            "type": robot_type,
                        },
                    )
                ).scalar_one()
            elif stage_label == "rollback":
                required = (
                    await session.execute(
                        sa.text("""
                            SELECT count(DISTINCT robot_id)
                            FROM platform_deployment_targets
                            WHERE tenant_id = :tenant AND domain_id = :domain
                              AND robot_type = :type AND candidate_version = :version
                              AND stage IN ('canary', 'fleet')
                              AND acknowledged_at IS NOT NULL
                        """),
                        {
                            "tenant": scope.tenant_id,
                            "domain": scope.domain_id,
                            "type": robot_type,
                            "version": candidate_version,
                        },
                    )
                ).scalar_one()
            else:
                required = counts.total
            if counts.total < required or counts.done < required:
                return current
            await self._write_transition(session, updated, None)
            return updated

    async def acknowledge_signed(self, ack: ModelAck) -> Deployment:
        """Accept only a fresh signature from the registered robot device key."""
        age = abs((datetime.now(UTC) - ack.occurred_at).total_seconds())
        if age > 300:
            raise PermissionError("model acknowledgement is stale")
        async with self.store._scoped(ack.scope) as session:
            public_key = (
                await session.execute(
                    sa.text("""
                        SELECT device_public_key FROM platform_units
                        WHERE tenant_id = :tenant AND domain_id = :domain
                          AND id = :robot AND robot_type = :type AND rank = 3
                    """),
                    {
                        "tenant": ack.scope.tenant_id,
                        "domain": ack.scope.domain_id,
                        "robot": ack.robot_id,
                        "type": ack.robot_type,
                    },
                )
            ).scalar_one_or_none()
            if public_key is None:
                raise PermissionError("robot device key is not registered")
            try:
                Ed25519PublicKey.from_public_bytes(public_key).verify(
                    bytes.fromhex(ack.signature), ack.signed_bytes()
                )
            except (InvalidSignature, ValueError) as exc:
                raise PermissionError("invalid robot acknowledgement signature") from exc
        return await self.acknowledge(
            ack.scope,
            ack.robot_id,
            ack.robot_type,
            ack.candidate_version,
            ack.applied_version,
            ack.stage,
        )

    async def _write_transition(
        self, session: AsyncSession, deployment: Deployment, approval_id: str | None
    ) -> None:
        scope = deployment.scope
        stage = deployment.stage
        await session.execute(
            sa.text("""
                UPDATE platform_deployments
                SET stage = :stage, updated_at = now(),
                    canary_approval_id = CASE WHEN :stage = 'canary_pending'
                        THEN CAST(:approval AS uuid) ELSE canary_approval_id END,
                    fleet_approval_id = CASE WHEN :stage = 'fleet_pending'
                        THEN CAST(:approval AS uuid) ELSE fleet_approval_id END
                WHERE tenant_id = :tenant AND domain_id = :domain
                  AND robot_type = :type AND candidate_version = :version
            """),
            {
                "stage": stage.value,
                "approval": approval_id,
                "tenant": scope.tenant_id,
                "domain": scope.domain_id,
                "type": deployment.robot_type,
                "version": deployment.candidate_version,
            },
        )
        event_id = str(uuid4())
        payload = {
            "robot_type": deployment.robot_type,
            "candidate_version": deployment.candidate_version,
            "previous_version": deployment.previous_version,
            "stage": stage.value,
            "approval_id": approval_id,
        }
        kind = (
            "ModelRollbackRequested"
            if stage is Stage.ROLLBACK_PENDING
            else "ModelDeploymentStateChanged"
        )
        await session.execute(
            sa.text("""
                INSERT INTO platform_events
                  (tenant_id, domain_id, id, kind, subject_id, schema_version,
                   occurred_at, payload)
                VALUES (:tenant, :domain, :id, :kind, :subject, 1,
                        :occurred, CAST(:payload AS jsonb))
            """),
            {
                "tenant": scope.tenant_id,
                "domain": scope.domain_id,
                "id": event_id,
                "kind": kind,
                "subject": deployment.robot_type,
                "occurred": datetime.now(UTC),
                "payload": json.dumps(payload),
            },
        )
        await session.execute(
            sa.text("""
                INSERT INTO platform_outbox (tenant_id, domain_id, event_id, payload)
                VALUES (:tenant, :domain, :id, CAST(:payload AS jsonb))
            """),
            {
                "tenant": scope.tenant_id,
                "domain": scope.domain_id,
                "id": event_id,
                "payload": json.dumps({"kind": kind, **payload}),
            },
        )
