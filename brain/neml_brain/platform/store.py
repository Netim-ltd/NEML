# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""PostgreSQL adapter for tenant-scoped events, episodes, and model metadata.

Every operation sets the RLS tenant in its own transaction. The database policy
is the second boundary after explicit tenant predicates in these statements.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from neml_brain.platform.core import Event, Scope
from neml_brain.platform.feedback import report_bytes, verify_report
from neml_brain.platform.learning import Episode
from neml_brain.platform.robots import ModelCard


class PlatformStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @asynccontextmanager
    async def _scoped(self, scope: Scope) -> AsyncIterator[AsyncSession]:
        async with self._sessions() as session, session.begin():
            await session.execute(
                sa.text("SELECT set_config('neml.tenant_id', :tenant, true)"),
                {"tenant": scope.tenant_id},
            )
            yield session

    async def append_event(self, event: Event) -> bool:
        """Write event and outbox atomically; duplicate ID is idempotent."""
        async with self._scoped(event.scope) as session:
            result = await session.execute(
                sa.text("""
                    INSERT INTO platform_events
                      (tenant_id, domain_id, id, kind, subject_id, schema_version,
                       occurred_at, payload)
                    VALUES (:tenant, :domain, :id, :kind, :subject, :version,
                            :occurred, CAST(:payload AS jsonb))
                    ON CONFLICT (tenant_id, domain_id, id) DO NOTHING
                    RETURNING id
                """),
                {
                    "tenant": event.scope.tenant_id,
                    "domain": event.scope.domain_id,
                    "id": event.id,
                    "kind": event.kind,
                    "subject": event.subject_id,
                    "version": event.schema_version,
                    "occurred": event.occurred_at,
                    "payload": json.dumps(event.payload),
                },
            )
            inserted = result.scalar_one_or_none() is not None
            if inserted:
                await session.execute(
                    sa.text("""
                        INSERT INTO platform_outbox (tenant_id, domain_id, event_id, payload)
                        VALUES (:tenant, :domain, :id, CAST(:payload AS jsonb))
                    """),
                    {
                        "tenant": event.scope.tenant_id,
                        "domain": event.scope.domain_id,
                        "id": event.id,
                        "payload": json.dumps(
                            {
                                "kind": event.kind,
                                "subject_id": event.subject_id,
                                "schema_version": event.schema_version,
                                "occurred_at": event.occurred_at.isoformat(),
                                "payload": event.payload,
                            }
                        ),
                    },
                )
            return inserted

    async def record_episode(self, episode: Episode) -> bool:
        async with self._scoped(episode.scope) as session:
            result = await session.execute(
                sa.text("""
                    INSERT INTO platform_episodes
                      (tenant_id, domain_id, id, robot_type, robot_id, model_version, observed_at,
                       observation_hash, action, outcome, reward, failure_class,
                       quality, features)
                    VALUES (:tenant, :domain, :id, :type, :robot, :model, :observed, :hash,
                            :action, :outcome, :reward, :failure, :quality,
                            CAST(:features AS jsonb))
                    ON CONFLICT (tenant_id, domain_id, id) DO NOTHING
                    RETURNING id
                """),
                {
                    "tenant": episode.scope.tenant_id,
                    "domain": episode.scope.domain_id,
                    "id": episode.id,
                    "type": episode.robot_type,
                    "robot": episode.robot_id,
                    "model": episode.model_version,
                    "observed": episode.observed_at,
                    "hash": episode.observation_hash,
                    "action": episode.action,
                    "outcome": episode.outcome,
                    "reward": episode.reward,
                    "failure": episode.failure_class,
                    "quality": episode.quality,
                    "features": json.dumps(episode.features),
                },
            )
            return result.scalar_one_or_none() is not None

    async def record_feedback(self, report: dict[str, Any]) -> bool:
        """Verify both device identities and commit one idempotent recovery event."""
        scope = Scope(report["tenant_id"], report["domain_id"])
        digest = hashlib.sha256(report_bytes(report)).hexdigest()
        async with self._scoped(scope) as session:
            robot_key = (
                await session.execute(
                    sa.text("""
                        SELECT device_public_key FROM platform_units
                        WHERE tenant_id = :tenant AND domain_id = :domain
                          AND id = :robot AND robot_type = :type AND rank = 3
                    """),
                    {
                        "tenant": scope.tenant_id,
                        "domain": scope.domain_id,
                        "robot": report["robot_id"],
                        "type": report["robot_type"],
                    },
                )
            ).scalar_one_or_none()
            verifier_key = (
                await session.execute(
                    sa.text("""
                        SELECT public_key FROM platform_verifiers
                        WHERE tenant_id = :tenant AND domain_id = :domain
                          AND id = :verifier AND active = TRUE
                    """),
                    {
                        "tenant": scope.tenant_id,
                        "domain": scope.domain_id,
                        "verifier": report["verifier_id"],
                    },
                )
            ).scalar_one_or_none()
            if robot_key is None or verifier_key is None:
                raise PermissionError("robot or outcome verifier is not registered")
            verify_report(report, bytes(robot_key), bytes(verifier_key))
            inserted = (
                await session.execute(
                    sa.text("""
                    INSERT INTO platform_feedback_reports
                      (tenant_id, domain_id, report_id, robot_id, operation,
                       occurred_at, payload, payload_sha256)
                    VALUES (:tenant, :domain, CAST(:id AS uuid), :robot, :operation,
                            :occurred, CAST(:payload AS jsonb), :digest)
                    ON CONFLICT (tenant_id, domain_id, report_id) DO NOTHING
                    RETURNING report_id
                """),
                    {
                        "tenant": scope.tenant_id,
                        "domain": scope.domain_id,
                        "id": report["report_id"],
                        "robot": report["robot_id"],
                        "operation": report["operation"],
                        "occurred": datetime.fromisoformat(report["occurred_at"]),
                        "payload": json.dumps(report),
                        "digest": digest,
                    },
                )
            ).scalar_one_or_none()
            if inserted is None:
                existing = (
                    await session.execute(
                        sa.text("""
                            SELECT payload_sha256 FROM platform_feedback_reports
                            WHERE tenant_id = :tenant AND domain_id = :domain
                              AND report_id = CAST(:id AS uuid)
                        """),
                        {
                            "tenant": scope.tenant_id,
                            "domain": scope.domain_id,
                            "id": report["report_id"],
                        },
                    )
                ).scalar_one()
                if existing != digest:
                    raise PermissionError("report ID already names different content")
                return False
            event_id = f"feedback:{report['report_id']}"
            event_payload = {
                "report_id": report["report_id"],
                "operation": report["operation"],
                "sha256": digest,
            }
            await session.execute(
                sa.text("""
                    INSERT INTO platform_events
                      (tenant_id, domain_id, id, kind, subject_id, schema_version,
                       occurred_at, payload)
                    VALUES (:tenant, :domain, :id, 'RecoveryVerified', :subject, 1,
                            :occurred, CAST(:payload AS jsonb))
                """),
                {
                    "tenant": scope.tenant_id,
                    "domain": scope.domain_id,
                    "id": event_id,
                    "subject": report["robot_id"],
                    "occurred": datetime.fromisoformat(report["occurred_at"]),
                    "payload": json.dumps(event_payload),
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
                        {
                            "kind": "RecoveryVerified",
                            "subject_id": report["robot_id"],
                            "schema_version": 1,
                            "occurred_at": report["occurred_at"],
                            "payload": event_payload,
                        }
                    ),
                },
            )
            return True

    async def export_feedback(
        self, scope: Scope, operation: str, after: str | None, limit: int = 100
    ) -> list[dict[str, Any]]:
        async with self._scoped(scope) as session:
            result = await session.execute(
                sa.text("""
                    SELECT f.report_id, f.payload, u.device_public_key, v.public_key
                    FROM platform_feedback_reports f
                    JOIN platform_units u
                      ON (u.tenant_id, u.domain_id, u.id) =
                         (f.tenant_id, f.domain_id, f.robot_id)
                    JOIN platform_verifiers v
                      ON (v.tenant_id, v.domain_id, v.id) =
                         (f.tenant_id, f.domain_id, f.payload->>'verifier_id')
                     AND v.active = TRUE
                    WHERE f.tenant_id = :tenant AND f.domain_id = :domain
                      AND f.operation = :operation
                      AND (CAST(:after AS uuid) IS NULL OR f.report_id > CAST(:after AS uuid))
                    ORDER BY f.report_id LIMIT :limit
                """),
                {
                    "tenant": scope.tenant_id,
                    "domain": scope.domain_id,
                    "operation": operation,
                    "after": after,
                    "limit": limit,
                },
            )
            return [
                {
                    "report": row.payload,
                    "robot_public_key": row.device_public_key.hex(),
                    "verifier_public_key": row.public_key.hex(),
                }
                for row in result
            ]

    async def list_for_training(self, scope: Scope, robot_type: str) -> list[Episode]:
        async with self._scoped(scope) as session:
            result = await session.execute(
                sa.text("""
                    SELECT id, robot_id, model_version, observed_at,
                           observation_hash, action, outcome,
                           reward, failure_class, quality, features
                    FROM platform_episodes
                    WHERE tenant_id = :tenant AND domain_id = :domain
                      AND robot_type = :type
                    ORDER BY observed_at DESC LIMIT 10000
                """),
                {"tenant": scope.tenant_id, "domain": scope.domain_id, "type": robot_type},
            )
            return [
                Episode(
                    id=row.id,
                    scope=scope,
                    robot_type=robot_type,
                    observed_at=row.observed_at,
                    observation_hash=row.observation_hash,
                    action=row.action,
                    outcome=row.outcome,
                    reward=float(row.reward),
                    failure_class=row.failure_class,
                    quality=float(row.quality),
                    features=tuple(float(x) for x in row.features),
                    robot_id=row.robot_id,
                    model_version=row.model_version,
                )
                for row in result
            ]

    async def validated_missions(self, scope: Scope, robot_type: str) -> int:
        """Only sensor-verified successes earn larger model budgets."""
        async with self._scoped(scope) as session:
            result = await session.execute(
                sa.text("""
                    SELECT count(*) FROM platform_episodes
                    WHERE tenant_id = :tenant AND domain_id = :domain
                      AND robot_type = :type AND outcome = 'success' AND quality >= 0.8
                """),
                {"tenant": scope.tenant_id, "domain": scope.domain_id, "type": robot_type},
            )
            return int(result.scalar_one())

    async def save_model(self, card: ModelCard, artifact_path: str) -> None:
        async with self._scoped(card.scope) as session:
            await session.execute(
                sa.text("""
                    INSERT INTO platform_models
                      (tenant_id, domain_id, robot_type, version, artifact_path,
                       artifact_sha256, signature, training_start, training_end,
                       metrics, rollback_version)
                    VALUES (:tenant, :domain, :type, :version, :path, :digest,
                            :signature, :start, :end, CAST(:metrics AS jsonb), :rollback)
                """),
                {
                    "tenant": card.scope.tenant_id,
                    "domain": card.scope.domain_id,
                    "type": card.robot_type,
                    "version": card.version,
                    "path": artifact_path,
                    "digest": card.artifact_sha256,
                    "signature": card.signature,
                    "start": card.training_start,
                    "end": card.training_end,
                    "metrics": json.dumps(card.metrics),
                    "rollback": card.rollback_version,
                },
            )
            if card.rollback_version is not None:
                await session.execute(
                    sa.text("""
                        INSERT INTO platform_deployments
                          (tenant_id, domain_id, robot_type, candidate_version,
                           previous_version, stage)
                        VALUES (:tenant, :domain, :type, :version, :previous, 'sim_validated')
                    """),
                    {
                        "tenant": card.scope.tenant_id,
                        "domain": card.scope.domain_id,
                        "type": card.robot_type,
                        "version": card.version,
                        "previous": card.rollback_version,
                    },
                )

    async def get_model(self, scope: Scope, robot_type: str, version: str) -> tuple[ModelCard, str]:
        async with self._scoped(scope) as session:
            row = (
                await session.execute(
                    sa.text("""
                        SELECT artifact_path, artifact_sha256, signature,
                               training_start, training_end, metrics, rollback_version
                        FROM platform_models
                        WHERE tenant_id = :tenant AND domain_id = :domain
                          AND robot_type = :type AND version = :version
                    """),
                    {
                        "tenant": scope.tenant_id,
                        "domain": scope.domain_id,
                        "type": robot_type,
                        "version": version,
                    },
                )
            ).one_or_none()
            if row is None:
                raise KeyError("model not found in tenant/domain")
            return (
                ModelCard(
                    scope,
                    robot_type,
                    version,
                    row.artifact_sha256,
                    row.signature,
                    row.training_start,
                    row.training_end,
                    {key: float(value) for key, value in row.metrics.items()},
                    row.rollback_version,
                ),
                row.artifact_path,
            )

    async def pending_outbox(self, scope: Scope, limit: int = 100) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1000:
            raise ValueError("outbox limit must be 1..1000")
        async with self._scoped(scope) as session:
            result = await session.execute(
                sa.text("""
                    SELECT event_id, payload, created_at FROM platform_outbox
                    WHERE tenant_id = :tenant AND domain_id = :domain
                      AND delivered_at IS NULL
                    ORDER BY created_at LIMIT :limit
                """),
                {"tenant": scope.tenant_id, "domain": scope.domain_id, "limit": limit},
            )
            return [dict(row._mapping) for row in result]

    async def mark_delivered(self, scope: Scope, event_id: str, when: datetime) -> None:
        async with self._scoped(scope) as session:
            await session.execute(
                sa.text("""
                    UPDATE platform_outbox SET delivered_at = :when
                    WHERE tenant_id = :tenant AND domain_id = :domain AND event_id = :id
                      AND delivered_at IS NULL
                """),
                {
                    "tenant": scope.tenant_id,
                    "domain": scope.domain_id,
                    "id": event_id,
                    "when": when,
                },
            )
