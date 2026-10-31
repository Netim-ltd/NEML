# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 5.2 deployment gates.

Level 0 (SIM) is automatic. Levels 1-4 need a row in `approvals` that a human
decided before it expired (default 24 h, SPEC 5.2). Level 4 is owner-only
(SPEC 5.5). There is deliberately no bypass flag and no parameter that skips
the wait: the only way past this gate is a decided row.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import IntEnum

from sqlalchemy import text

from neml_brain.api.metrics import APPROVAL_PENDING_COUNT  # SPEC 18.3, declared once
from neml_brain.runtime.audit import AuditLog, SessionFactory

DEFAULT_TTL = timedelta(hours=24)  # SPEC 5.2
DEFAULT_POLL_INTERVAL_S = 5.0


class Level(IntEnum):
    SIM = 0
    BENCH = 1
    TETHERED = 2
    FREE = 3
    MANUFACTURE = 4


OWNER_ONLY = frozenset({Level.MANUFACTURE})  # SPEC 5.5


class ApprovalDenied(PermissionError):
    pass


class ApprovalExpired(ApprovalDenied):
    pass


@dataclass(frozen=True, slots=True)
class Approval:
    id: str | None  # None only for level 0, which creates no row
    level: Level
    decided_by: str | None


_INSERT = text(
    "INSERT INTO approvals (level, subject_kind, subject_id, payload, expires_at)"
    " VALUES (:level, :subject_kind, :subject_id, CAST(:payload AS jsonb), :expires_at)"
    " RETURNING id"
)
_POLL = text("SELECT decision, decided_by, expires_at FROM approvals WHERE id = CAST(:id AS uuid)")
_SETTLE = text(
    "UPDATE approvals SET decision = :decision, decided_at = now(), note = :note"
    " WHERE id = CAST(:id AS uuid) AND decision IS NULL"
)
# The owner-only override deliberately overwrites an existing 'approved' row.
_OVERRIDE = text(
    "UPDATE approvals SET decision = :decision, decided_at = now(), note = :note"
    " WHERE id = CAST(:id AS uuid)"
)


def _owners_from_env() -> frozenset[str]:
    """Empty by default: an unconfigured lab cannot approve level 4 at all."""
    return frozenset(o.strip() for o in os.getenv("NEML_OWNERS", "").split(",") if o.strip())


class DeploymentGate:
    def __init__(
        self,
        session_factory: SessionFactory,
        audit: AuditLog,
        *,
        ttl: timedelta = DEFAULT_TTL,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        owners: Collection[str] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._audit = audit
        self._ttl = ttl
        self._poll_interval_s = poll_interval_s
        # ponytail: the `users` table is cloud-only (SPEC 7), so the lab cannot join on
        # role. Owners come from NEML_OWNERS. Upgrade path: have the bridge stamp the
        # decider's role into approvals.note and verify that instead.
        self._owners = frozenset(owners) if owners is not None else _owners_from_env()

    async def require_approval(
        self,
        level: Level | int,
        subject_kind: str,
        subject_id: str,
        payload: object,
    ) -> Approval:
        level = Level(level)
        if level is Level.SIM:
            await self._audit.write(
                actor="gate",
                action=f"level{level}",
                target=f"{subject_kind}:{subject_id}",
                params=payload,
                outcome="auto_approved",
            )
            return Approval(None, level, None)

        started = time.monotonic()
        expires_at = datetime.now(UTC) + self._ttl
        approval_id = str(await self._insert(level, subject_kind, subject_id, payload, expires_at))
        APPROVAL_PENDING_COUNT.inc()
        try:
            return await self._wait(approval_id, level, subject_kind, subject_id, started)
        finally:
            APPROVAL_PENDING_COUNT.dec()

    async def _insert(
        self,
        level: Level,
        subject_kind: str,
        subject_id: str,
        payload: object,
        expires_at: datetime,
    ) -> object:
        async with self._session_factory() as session:
            result = await session.execute(
                _INSERT,
                {
                    "level": int(level),
                    "subject_kind": subject_kind,
                    "subject_id": subject_id,
                    "payload": json.dumps(payload, default=str),
                    "expires_at": expires_at,
                },
            )
            new_id = result.scalar_one()
            await session.commit()
            return new_id

    async def _wait(
        self,
        approval_id: str,
        level: Level,
        subject_kind: str,
        subject_id: str,
        started: float,
    ) -> Approval:
        target = f"{subject_kind}:{subject_id}"
        while True:
            decision, decided_by, expires_at = await self._read(approval_id)
            if decision is None and datetime.now(UTC) >= expires_at:
                await self._settle(approval_id, "expired", "ttl elapsed")
                await self._finish(level, target, started, "expired", approval_id)
                raise ApprovalExpired(f"approval {approval_id} expired without a decision")
            if decision == "approved":
                if level in OWNER_ONLY and decided_by not in self._owners:
                    await self._settle(
                        approval_id, "rejected", "level 4 is owner-only", override=True
                    )
                    await self._finish(level, target, started, "denied:not_owner", approval_id)
                    raise ApprovalDenied(f"level {int(level)} may only be approved by an owner")
                await self._finish(level, target, started, "approved", approval_id)
                return Approval(approval_id, level, decided_by)
            if decision == "expired":
                await self._finish(level, target, started, "expired", approval_id)
                raise ApprovalExpired(f"approval {approval_id} expired")
            if decision is not None:
                await self._finish(level, target, started, f"denied:{decision}", approval_id)
                raise ApprovalDenied(f"approval {approval_id} was {decision}")
            remaining = (expires_at - datetime.now(UTC)).total_seconds()
            await asyncio.sleep(max(0.0, min(self._poll_interval_s, remaining)))

    async def _read(self, approval_id: str) -> tuple[str | None, str | None, datetime]:
        async with self._session_factory() as session:
            row = (await session.execute(_POLL, {"id": approval_id})).one()
            decision, decided_by, expires_at = row
            return decision, decided_by, expires_at

    async def _settle(
        self, approval_id: str, decision: str, note: str, *, override: bool = False
    ) -> None:
        async with self._session_factory() as session:
            await session.execute(
                _OVERRIDE if override else _SETTLE,
                {"id": approval_id, "decision": decision, "note": note},
            )
            await session.commit()

    async def _finish(
        self, level: Level, target: str, started: float, outcome: str, approval_id: str
    ) -> None:
        await self._audit.write(
            actor="gate",
            action=f"level{int(level)}",
            target=target,
            outcome=outcome,
            duration_ms=int((time.monotonic() - started) * 1000),
            approval_id=approval_id,
        )
