# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lab -> cloud live feed: what the app screens show (SPEC 9.4, 9.5).

The cloud only relays what the lab sends, and it accepts exactly the ten SPEC 9.4
event names with camelCase payloads. Nothing in the brain emitted them, so the
dashboard, robot and task screens stayed empty. This module polls the lab
database on small intervals and sends the four things those screens need:

    BrainStatus event   online, model, GPU owner, budget used
    `state` envelope    one robot's mirror row (id, state, battery, last seen)
    TaskUpdated event   a task whose state changed since the last look
    `telemetry` batch   new samples since the last cursor

Polling is deliberate: it covers rows written by *any* process (the brain, the
autonomy service, the ROS bridge) without each of them knowing about the link.
Everything goes through CloudBridge.send, which works offline and drains on
reconnect, and telemetry is the only droppable type (SPEC 9.5).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

TELEMETRY_BATCH = 500
AUDIT_BATCH = 200
_PROGRESS = {
    "queued": 0.0,
    "planning": 0.1,
    "awaiting_approval": 0.2,
    "running": 0.5,
    "paused": 0.5,
    "succeeded": 1.0,
    "failed": 1.0,
    "cancelled": 1.0,
}


def iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


class LivePublisher:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        send: Callable[..., Any],
        *,
        model: str,
        budget_used: Callable[[], Awaitable[float]],
        gpu_owner: Callable[[], str | None],
    ) -> None:
        self._sessions, self._send, self._model = sessions, send, model
        self._budget_used, self._gpu_owner = budget_used, gpu_owner
        self._task_states: dict[str, str] = {}
        self._robot_states: dict[str, tuple[Any, ...]] = {}
        self._since = datetime.now(UTC)
        self._boundary: set[tuple[Any, ...]] = set()  # rows already sent at `_since`
        self._primed = False
        self._audit_cursor = 0

    def _event(self, name: str, data: dict[str, Any]) -> None:
        self._send("event", {"name": name, "data": data})

    async def brain_status(self) -> None:
        self._event(
            "BrainStatus",
            {
                "online": True,
                "model": self._model,
                "gpuOwner": self._gpu_owner(),
                "budgetUsed": round(await self._budget_used(), 4),
            },
        )

    async def robots(self) -> int:
        sql = sa.text("SELECT id, state, battery_soc::float AS soc, last_seen FROM robots")
        async with self._sessions() as session:
            rows = (await session.execute(sql)).all()
        sent = 0
        for r in rows:
            key = (r.state, r.soc, r.last_seen)
            if self._robot_states.get(r.id) == key:
                continue
            self._robot_states[r.id] = key
            self._send(
                "state",
                {
                    "robotId": r.id,
                    "state": r.state,
                    "batterySoc": r.soc,
                    "lastSeen": iso(r.last_seen),
                },
            )
            sent += 1
        return sent

    async def tasks(self) -> int:
        sql = sa.text(
            "SELECT id::text AS id, state, result->>'parked' AS note FROM tasks"
            " WHERE updated_at > now() - interval '1 day'"
        )
        async with self._sessions() as session:
            rows = (await session.execute(sql)).all()
        first_look, self._primed = not self._primed, True
        sent = 0
        for r in rows:
            changed = self._task_states.get(r.id) != r.state
            self._task_states[r.id] = r.state
            if first_look or not changed:  # the app loads current rows over REST
                continue
            self._event(
                "TaskUpdated",
                {
                    "taskId": r.id,
                    "state": r.state,
                    "progress": _PROGRESS.get(r.state, 0.0),
                    "message": r.note,
                },
            )
            sent += 1
        return sent

    async def telemetry(self) -> int:
        sql = sa.text(
            "SELECT ts, robot_id, metric, value, tags FROM telemetry WHERE ts >= :since"
            " ORDER BY ts LIMIT :n"
        )
        async with self._sessions() as session:
            rows = (await session.execute(sql, {"since": self._since, "n": TELEMETRY_BATCH})).all()
        rows = [r for r in rows if (r.ts, r.robot_id, r.metric) not in self._boundary]
        if not rows:
            return 0
        # Several metrics share one timestamp, so `>` would lose the rest of a tick that
        # straddles a batch edge: re-read from the last ts and skip what was already sent.
        last = rows[-1].ts
        if last != self._since:
            self._boundary.clear()
        self._since = last
        self._boundary |= {(r.ts, r.robot_id, r.metric) for r in rows if r.ts == last}
        self._send(
            "telemetry",
            {
                "samples": [
                    {
                        "ts": iso(r.ts),
                        "robotId": r.robot_id,
                        "metric": r.metric,
                        "value": r.value,
                        "tags": r.tags,
                    }
                    for r in rows
                ]
            },
        )
        return len(rows)

    async def audit(self) -> int:
        """New audit_log rows as one durable `log` envelope; the cloud mirrors them (screen 12)."""
        sql = sa.text(
            "SELECT id, ts, actor, action, target, outcome, duration_ms, approval_id::text AS aid"
            " FROM audit_log WHERE id > :cursor AND ts > now() - interval '1 day'"
            " ORDER BY id LIMIT :n"
        )
        async with self._sessions() as session:
            rows = (
                await session.execute(sql, {"cursor": self._audit_cursor, "n": AUDIT_BATCH})
            ).all()
        if not rows:
            return 0
        self._audit_cursor = rows[-1].id
        self._send(
            "log",
            {
                "level": "audit",
                "message": f"{len(rows)} audit entries",
                "audit": [
                    {
                        "ts": iso(r.ts),
                        "actor": r.actor,
                        "action": r.action,
                        "target": r.target,
                        "outcome": r.outcome,
                        "durationMs": r.duration_ms,
                        "approvalId": r.aid,
                    }
                    for r in rows
                ],
            },
        )
        return len(rows)
