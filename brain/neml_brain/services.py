# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Runtime service facades — the objects main.py's lifespan puts on ``app.state``.

Everything below adapts a module that already exists (db/, llm/, mcp/, agents/,
safety/, bridge/, evolution/, runtime/) to the handle contract the SPEC 8.3
routers use via api/deps.py. No logic lives here that is not wiring: a facade
either delegates, or runs the one statement its endpoint needs.

Nothing here talks to the model. The SPEC 8.4 graph classifies and fills
schemas; every MCP call below is named by a node, never chosen (SPEC 6.5).

ponytail: plain classes, no DI container. Ten objects built once at startup do
not need a framework; the day this graph of handles stops fitting in one
lifespan function is the day to reach for one.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import hashlib
import json
import os
import time
import uuid
from collections.abc import Sequence
from contextlib import AsyncExitStack
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

import httpx
import sqlalchemy as sa
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from neml_brain.agents import orchestrator as graph_module
from neml_brain.agents.base import Deps
from neml_brain.api.metrics import SIM_RUNS
from neml_brain.bridge.client import CloudBridge
from neml_brain.bridge.outbox import Outbox
from neml_brain.bridge.protocol import Envelope
from neml_brain.db import repo
from neml_brain.db.models import (
    Approval,
    Base,
    Genome,
    Robot,
    SafetyCheck,
    Skill,
    Task,
    TaskRun,
    Telemetry,
)
from neml_brain.llm.provider import LLMProvider
from neml_brain.logging import get_logger
from neml_brain.mcp import registry
from neml_brain.mcp.client import McpClient, McpConfigError
from neml_brain.runtime.audit import AuditLog
from neml_brain.runtime.budget import Budget
from neml_brain.runtime.gpu_lock import GpuLock
from neml_brain.safety.gates import DEFAULT_TTL, OWNER_ONLY, Level

if TYPE_CHECKING:
    from sqlalchemy.engine import CursorResult

log = get_logger(__name__)

Sessions = async_sessionmaker[AsyncSession]

# SPEC 5.4 grants agents logical tool names; SPEC 6.5 says a node names its tool
# statically. This table is the only place a logical name becomes a server and a
# remote tool. The model never sees it and cannot extend it at runtime.
TOOL_ROUTES: dict[str, tuple[str, str]] = {
    "cad.generate": ("freecad", "build_recipe"),
    "cad.export": ("freecad", "convert"),
    "sim.run": ("sim", "run_until"),
    "sim.read": ("sim", "get_metrics"),
    "slicer.slice": ("fab", "slice"),
    "gcode.validate": ("fab", "validate_gcode"),
    "printer.start": ("fab", "start"),
    "printer.status": ("fab", "status"),
    "kicad.generate": ("kicad", "build_circuit"),
    "kicad.drc": ("kicad", "run_drc"),
    "kicad.bom": ("kicad", "export_bom"),
    "kicad.gerber_export": ("kicad", "export_gerber"),
    "genome.read": ("genome", "read"),
    "db.read": ("postgres", "query"),
    "skill.read": ("postgres", "query"),
}

# SPEC 7 tasks.state — the non-terminal half. A finished task is never re-opened.
OPEN_TASK_STATES = ("queued", "planning", "awaiting_approval", "running", "paused")


def _jsonable(value: object) -> Any:
    """SPEC 8.3 answers are `application/json`; Numeric/uuid/timestamp are not."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def _row(obj: Base) -> dict[str, Any]:
    """A mapped instance as the flat dict the routers hand to FastAPI."""
    return {name: _jsonable(getattr(obj, name)) for name in sa.inspect(type(obj)).columns.keys()}


def _rows(objs: Sequence[Base]) -> list[dict[str, Any]]:
    return [_row(obj) for obj in objs]


def _mapping(row: Any) -> dict[str, Any]:
    """A RETURNING row as the same flat dict `_row` produces."""
    return {key: _jsonable(value) for key, value in dict(row).items()}


def _rowcount(result: Any) -> int:
    return cast("CursorResult[Any]", result).rowcount


class Db:
    """`app.state.repo` and the SPEC 8.4 `Deps.db`.

    db/repo.py stays what it is — free functions over a session. This class is
    the session-owning shell around them, plus the handful of CRUD statements
    the SPEC 8.3 routers need and nothing else did.
    """

    def __init__(self, sessions: Sessions, audit_log: AuditLog) -> None:
        self._sessions = sessions
        self._audit = audit_log

    # --- SPEC 8.3 read/write surface --------------------------------------
    async def ping(self) -> str:
        async with self._sessions() as session:
            return str((await session.execute(sa.text("SELECT version()"))).scalar_one())

    async def list_robots(self) -> list[dict[str, Any]]:
        async with self._sessions() as session:
            result = await session.execute(sa.select(Robot).order_by(Robot.id))
            return _rows(result.scalars().all())

    async def get_robot(self, robot_id: str) -> dict[str, Any] | None:
        async with self._sessions() as session:
            robot = await session.get(Robot, robot_id)
            return None if robot is None else _row(robot)

    async def list_tasks(
        self,
        *,
        state: str | None = None,
        kind: str | None = None,
        robot_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """SPEC 14.2 queue order: priority DESC, ties by created_at ASC."""
        stmt = sa.select(Task).order_by(Task.priority.desc(), Task.created_at.asc())
        if state is not None:
            stmt = stmt.where(Task.state == state)
        if kind is not None:
            stmt = stmt.where(Task.kind == kind)
        if robot_id is not None:
            stmt = stmt.where(Task.robot_id == robot_id)
        async with self._sessions() as session:
            result = await session.execute(stmt.limit(limit).offset(offset))
            return _rows(result.scalars().all())

    async def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        values = dict(payload)
        deadline = values.get("deadline")
        if isinstance(deadline, str):  # TaskCreate dumps json mode; the column is timestamptz
            values["deadline"] = dt.datetime.fromisoformat(deadline)
        values.setdefault("state", "queued")
        async with self._sessions() as session:
            created = await session.execute(
                sa.insert(Task).values(**values).returning(*Task.__table__.c)
            )
            row = _mapping(created.mappings().one())
            await session.commit()
        return row

    async def update_task(self, task_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        async with self._sessions() as session:
            updated = await session.execute(
                sa.update(Task)
                .where(Task.id == task_id)
                .values(**changes, updated_at=sa.func.now())
                .returning(*Task.__table__.c)
            )
            row = updated.mappings().one_or_none()
            await session.commit()
        return None if row is None else _mapping(row)

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel, not delete: SPEC 7 keeps the row with state `cancelled`."""
        return await self.update_task(task_id, {"state": "cancelled"}) is not None

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        async with self._sessions() as session:
            task = await session.get(Task, task_id)
            return None if task is None else _row(task)

    async def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        """Any decision state, unlike pending_approvals: a decided one is still readable."""
        async with self._sessions() as session:
            approval = await session.get(Approval, approval_id)
            return None if approval is None else _row(approval)

    async def list_task_runs(self, task_id: str) -> list[dict[str, Any]] | None:
        """None means the task itself does not exist, which is the 404."""
        async with self._sessions() as session:
            if await session.get(Task, task_id) is None:
                return None
            result = await session.execute(
                sa.select(TaskRun).where(TaskRun.task_id == task_id).order_by(TaskRun.attempt)
            )
            return _rows(result.scalars().all())

    async def list_skills(
        self,
        *,
        skill_key: str | None = None,
        status: str | None = None,
        genome_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Each row carries its rolling success rate: SPEC 14.6 turns anything
        under 0.70 into an automatic repair task."""
        stmt = sa.select(Skill).order_by(Skill.skill_key, Skill.version.desc())
        if skill_key is not None:
            stmt = stmt.where(Skill.skill_key == skill_key)
        if status is not None:
            stmt = stmt.where(Skill.status == status)
        if genome_id is not None:
            stmt = stmt.where(Skill.genome_id == genome_id)
        async with self._sessions() as session:
            result = await session.execute(stmt.limit(limit))
            skills = _rows(result.scalars().all())
            for skill in skills:
                skill["success_rate"] = await repo.skill_success_rate(session, str(skill["id"]))
        return skills

    async def genome_lineage(
        self, *, root_id: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        """Flat rows carrying `parent_id`; the client draws the tree.

        ponytail: `root_id` filters one hop, not a recursive CTE. A lab with a
        few dozen genomes fits in one page; add WITH RECURSIVE the day it does not.
        """
        stmt = sa.select(Genome).order_by(Genome.created_at)
        if root_id is not None:
            stmt = stmt.where(sa.or_(Genome.id == root_id, Genome.parent_id == root_id))
        if status is not None:
            stmt = stmt.where(Genome.status == status)
        async with self._sessions() as session:
            result = await session.execute(stmt)
            return _rows(result.scalars().all())

    async def pending_approvals(self) -> list[dict[str, Any]]:
        async with self._sessions() as session:
            return _rows(await repo.pending_approvals(session))

    async def query_telemetry(
        self,
        *,
        robot_id: str,
        metric: str,
        start: dt.datetime | None = None,
        end: dt.datetime | None = None,
        bucket_s: int | None = None,
        limit: int = 1000,
        after: dt.datetime | None = None,
    ) -> list[dict[str, Any]]:
        end = end or dt.datetime.now(dt.UTC)
        start = start or end - dt.timedelta(hours=1)
        async with self._sessions() as session:
            if bucket_s is None:
                raw = await repo.telemetry_range(
                    session,
                    robot_id=robot_id,
                    metric=metric,
                    start=start,
                    end=end,
                    limit=limit,
                    after=after,
                )
                return [{**_row(row), "bucket_s": None} for row in raw]
            # SPEC 7 retention: past the 90 day raw window the answer is an
            # average. date_bin keeps buckets aligned between queries.
            bucket = sa.func.date_bin(
                sa.func.make_interval(0, 0, 0, 0, 0, 0, bucket_s),
                Telemetry.ts,
                sa.func.to_timestamp(0),
            )
            stmt = sa.select(bucket.label("ts"), sa.func.avg(Telemetry.value).label("value")).where(
                Telemetry.robot_id == robot_id,
                Telemetry.metric == metric,
                Telemetry.ts >= start,
                Telemetry.ts < end,
            )
            if after is not None:  # a bucket is identified by its start, so `>` skips whole pages
                stmt = stmt.having(bucket > after)
            result = await session.execute(stmt.group_by(bucket).order_by(bucket).limit(limit))
            return [
                {
                    "ts": _jsonable(row.ts),
                    "robot_id": robot_id,
                    "metric": metric,
                    "value": float(row.value),
                    "bucket_s": bucket_s,
                }
                for row in result
            ]

    async def ensure_telemetry_partitions(self) -> None:
        """Call the SPEC 7 partition function for this month and the next.

        The function is CREATE TABLE IF NOT EXISTS, so a daily call costs a
        catalogue lookup and guarantees next month's partition exists long
        before the first insert of the month needs it.
        """
        async with self._sessions() as session:
            await session.execute(sa.text("SELECT neml_ensure_telemetry_partition(current_date)"))
            await session.execute(
                sa.text(
                    "SELECT neml_ensure_telemetry_partition"
                    "((current_date + interval '1 month')::date)"
                )
            )
            await session.commit()

    # --- SPEC 8.4 Deps.db -------------------------------------------------
    async def query(self, *, intent: str | None, command: str, actor: str) -> list[dict[str, Any]]:
        """QUERY node. Three read intents, three statements, no model involved."""
        if intent == "query_skill":
            return await self.list_skills(limit=50)
        if intent == "query_telemetry":
            async with self._sessions() as session:
                result = await session.execute(
                    sa.select(Telemetry).order_by(Telemetry.ts.desc()).limit(50)
                )
                return _rows(result.scalars().all())
        if intent == "query_status":
            return [await self.system_status()]
        return await self.list_robots()

    async def system_status(self) -> dict[str, Any]:
        """One row an operator can read: what the lab is doing and what waits for a human."""
        async with self._sessions() as session:

            async def count(sql: str) -> dict[str, int]:
                rows = (await session.execute(sa.text(sql))).all()
                return {str(r[0]): int(r[1]) for r in rows}

            tasks = await count(
                "SELECT state, count(*) FROM tasks WHERE updated_at > now() - interval '1 day'"
                " GROUP BY state"
            )
            campaigns = await count("SELECT state, count(*) FROM campaigns GROUP BY state")
            waiting = await count(
                "SELECT subject_kind, count(*) FROM approvals WHERE decision IS NULL"
                " AND expires_at > now() GROUP BY subject_kind"
            )
            genome = (
                await session.execute(
                    sa.text(
                        "SELECT id, fitness_score::float FROM genomes WHERE status = 'active'"
                        " ORDER BY created_at DESC LIMIT 1"
                    )
                )
            ).first()
            robots = await count("SELECT state, count(*) FROM robots GROUP BY state")
        return {
            "tasks_last_24h": tasks,
            "campaigns": campaigns,
            "approvals_waiting": waiting,
            "active_genome": None if genome is None else {"id": genome[0], "fitness": genome[1]},
            "robots": robots,
        }

    async def task_op(
        self, *, intent: str | None, command: str, actor: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """TASK_OPS node.

        TASK_FILL (guided_json, ADR-014) runs first, so `params` carries the
        title, priority and task id the operator named. Update and cancel say so
        when the id is missing.
        """
        if intent == "create_task":
            return await self.create_task(
                {
                    "title": str(params.get("title") or command)[:200],
                    "kind": "human",
                    "source": f"user:{actor}",
                    "priority": float(params.get("priority", 500)),
                    "spec": {"command": command, **params},
                }
            )
        task_id = params.get("task_id")
        if not isinstance(task_id, str):
            return {"ok": False, "reason": f"{intent} needs params.task_id"}
        try:
            task_id = str(uuid.UUID(task_id))
        except ValueError:
            # The model fills task_id from free text and invents ids; that must be a refusal,
            # not an invalid-UUID error from Postgres surfacing as a 500.
            return {"ok": False, "reason": f"{task_id!r} is not a task id"}
        if intent == "cancel_task":
            return {"ok": await self.cancel_task(task_id), "task_id": task_id}
        patched = await self.update_task(task_id, {"spec": {"command": command, **params}})
        return {"ok": patched is not None, "task": patched}

    async def create_approval(
        self,
        *,
        level: int,
        subject_kind: str,
        subject_id: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> str:
        """SPEC 5.2 approval row, TTL from safety/gates.

        Idempotent on (subject_kind, subject_id): the APPROVAL node replays from
        the top when a human resumes the interrupt, and `idempotency_key` is
        derived from the same thread id, so a replay must not open a second row.
        """
        async with self._sessions() as session:
            open_row = await session.execute(
                sa.select(Approval.id).where(
                    Approval.subject_kind == subject_kind,
                    Approval.subject_id == subject_id,
                    Approval.decision.is_(None),
                )
            )
            found = open_row.scalars().first()
            if found is not None:
                return str(found)
            created = await session.execute(
                sa.insert(Approval)
                .values(
                    level=level,
                    subject_kind=subject_kind,
                    subject_id=subject_id,
                    payload=payload,
                    expires_at=dt.datetime.now(dt.UTC) + DEFAULT_TTL,
                )
                .returning(Approval.id)
            )
            approval_id = str(created.scalar_one())
            await session.commit()
        return approval_id

    async def persist(self, snapshot: dict[str, Any]) -> None:
        """SPEC 8.4 PERSIST.

        ponytail: no-op on purpose. The PostgreSQL checkpointer already wrote
        this exact state after every node and `audit()` below is the two-year
        record, so a third copy would only be a third thing to keep in sync.
        Upgrade path: index generated files into SPEC 7 `artifacts` here, once a
        generator returns a path and a sha256 to index.
        """

    async def audit(
        self,
        *,
        actor: str,
        action: str,
        target: str | None = None,
        params_hash: str | None = None,
        outcome: str | None = None,
        duration_ms: int | None = None,
        approval_id: str | None = None,
    ) -> None:
        """SPEC 5.4 audit row. `params_hash` arrives hashed from agents/base.py:
        raw parameters can carry untrusted text and this table is kept two years."""
        async with self._sessions() as session:
            await session.execute(
                sa.text(
                    "INSERT INTO audit_log"
                    " (actor, action, target, params_hash, outcome, duration_ms, approval_id)"
                    " VALUES (:actor, :action, :target, :params_hash, :outcome, :duration_ms,"
                    " CAST(:approval_id AS uuid))"
                ),
                {
                    "actor": actor,
                    "action": action,
                    "target": target,
                    "params_hash": params_hash,
                    "outcome": outcome,
                    "duration_ms": duration_ms,
                    "approval_id": approval_id,
                },
            )
            await session.commit()


class Safety:
    """SPEC 5.1 software e-stop and the SPEC 5.2/5.5 approval decision."""

    def __init__(self, sessions: Sessions, audit_log: AuditLog, owners: frozenset[str]) -> None:
        self._sessions = sessions
        self._audit = audit_log
        self._owners = owners

    async def software_estop(
        self, *, robot_id: str, actor: str, reason: str
    ) -> dict[str, Any] | None:
        """L1 only. The L0 relay of SPEC 5.1 is electrically independent of this
        and of every other line in this repository."""
        async with self._sessions() as session:
            stopped = await session.execute(
                sa.update(Robot)
                .where(Robot.id == robot_id)
                .values(state="estop")
                .returning(Robot.id)
            )
            if stopped.scalar_one_or_none() is None:
                return None
            cancelled = await session.execute(
                sa.update(Task)
                .where(Task.robot_id == robot_id, Task.state.in_(OPEN_TASK_STATES))
                .values(state="cancelled", updated_at=sa.func.now())
            )
            count = _rowcount(cancelled)
            await session.commit()
        await self._audit.write(
            actor=actor,
            action="robot.estop",
            target=robot_id,
            params={"reason": reason},
            outcome="ok",
        )
        return {"state": "estop", "actor": actor, "reason": reason, "cancelled_tasks": count}

    async def record_safety_check(
        self,
        *,
        robot_id: str,
        estop_ok: bool,
        watchdog_ok: bool,
        current_limit_ok: bool,
        performed_by: str,
    ) -> dict[str, Any] | None:
        """SAFETY.md section 0: the human-attested pre-session test (SPEC 5.1).

        A failing row is stored too: the *newest* row decides, so a later failed test
        withdraws an earlier pass (safety/preflight.py). None means no such robot.
        """
        async with self._sessions() as session:
            exists = await session.execute(sa.select(Robot.id).where(Robot.id == robot_id))
            if exists.scalar_one_or_none() is None:
                return None
            row = (
                (
                    await session.execute(
                        sa.insert(SafetyCheck)
                        .values(
                            robot_id=robot_id,
                            estop_ok=estop_ok,
                            watchdog_ok=watchdog_ok,
                            current_limit_ok=current_limit_ok,
                            performed_by=performed_by,
                        )
                        .returning(*SafetyCheck.__table__.c)
                    )
                )
                .mappings()
                .one()
            )
            await session.commit()
        passed = estop_ok and watchdog_ok and current_limit_ok
        await self._audit.write(
            actor=performed_by,
            action="safety_check.record",
            target=robot_id,
            params={"estop": estop_ok, "watchdog": watchdog_ok, "current_limit": current_limit_ok},
            outcome="pass" if passed else "fail",
        )
        return {**_mapping(row), "passed": passed}

    async def decide_approval(
        self, *, approval_id: str, decision: str, decided_by: str, note: str | None = None
    ) -> dict[str, Any] | None:
        """SPEC 5.5 — level 4 is owner-only, re-checked here and not at the edge.

        A caller the lab does not know as an owner cannot approve a level 4
        request whatever the .NET API claimed about their role.
        """
        async with self._sessions() as session:
            approval = await session.get(Approval, approval_id)
            if approval is None:
                return None
            if approval.decision is not None:  # already decided: api/approvals.py -> 409
                return _row(approval)
            if approval.expires_at <= dt.datetime.now(dt.UTC):
                decision, note = "expired", "approval window elapsed"
            if (
                decision == "approved"
                and Level(approval.level) in OWNER_ONLY
                and decided_by not in self._owners
            ):
                decision, note = "rejected", "level 4 may only be approved by an owner"
            settled = await session.execute(
                sa.update(Approval)
                .where(Approval.id == approval_id, Approval.decision.is_(None))
                .values(
                    decision=decision,
                    decided_by=decided_by,
                    decided_at=dt.datetime.now(dt.UTC),
                    note=note,
                )
                .returning(*Approval.__table__.c)
            )
            row = _mapping(settled.mappings().one())
            await session.commit()
        await self._audit.write(
            actor=decided_by,
            action=f"approval.{decision}",
            target=approval_id,
            outcome=decision,
            approval_id=approval_id,
        )
        return row

    async def expire_approvals(self) -> int:
        """SPEC 5.2 sweep: a request that outlived its window is auto-rejected."""
        async with self._sessions() as session:
            expired = await repo.expire_approvals(session)
            await session.commit()
        return expired


class BudgetService:
    """API facade for the persisted asynchronous budget ledger."""

    def __init__(self, budget: Budget) -> None:
        self.budget = budget

    async def allow(self, resource: str) -> bool:
        """SPEC 14.4 — at the limit the request is refused and the queue waits."""
        return await self.budget.ratio(resource) < 1.0

    async def snapshot(self) -> dict[str, Any]:
        return {"resources": await self.budget.snapshot()}

    async def reset_daily(self) -> None:
        """00:00 TRT. Budget rolls each window lazily, so reading the snapshot at
        the reset moment is what actually zeroes the counters and the gauges."""
        await self.budget.snapshot()


def adapt_params(tool: str, params: dict[str, Any]) -> dict[str, Any]:
    """Logical tool arguments -> the MCP tool's own signature.

    The design nodes already hand over what the CAD and KiCad servers take (a recipe or a circuit,
    a name and an output folder under the shared artifact volume), so nothing is rewritten here.
    """
    return params


class Mcp:
    """MCP health for /health, and the logical-name routing agents/base.py calls."""

    def __init__(self, client: McpClient) -> None:
        self.client = client

    async def health(self) -> dict[str, dict[str, Any]]:
        """T-016 — every server in config/mcp.yaml, green or red, never omitted."""
        return await registry.health_snapshot(self.client)

    async def call(self, tool: str, params: dict[str, Any]) -> Any:
        if tool == "sim.run":
            return await self._design_sim(params)
        try:
            server, name = TOOL_ROUTES[tool]
        except KeyError:
            raise McpConfigError(f"no MCP route for logical tool '{tool}'") from None
        return await self.client.call(server, name, adapt_params(tool, params))

    async def _design_sim(self, params: dict[str, Any]) -> dict[str, Any]:
        """The SIMULATE stage of a design change: seed -> load_world -> run -> teardown.

        ponytail: a smoke run. It proves the world loads and steps for the design's seed; the
        changed part is not yet re-exported into the robot URDF, so it is not scored. Scoring a
        part needs the URDF regeneration step (PhysicsRunner is the scoring path).
        """
        digest = hashlib.sha256(json.dumps(params.get("params"), sort_keys=True).encode()).digest()
        run = await Sim(self.client).run_once(
            {
                "world_id": os.environ.get("NEML_DESIGN_SIM_WORLD", "flat"),
                "seed": int.from_bytes(digest[:4], "big"),
                "profile": "fast",
                "duration_s": float(os.environ.get("NEML_DESIGN_SIM_S", "10")),
            }
        )
        return {"ok": run.get("outcome") == "success", "kind": "smoke", **run}

    async def aclose(self) -> None:
        await self.client.aclose()


class Sim:
    """`app.state.sim` — POST /v1/sim/run choreographed over SPEC 6.3 calls."""

    # The sim server's own timeout bounds the run; leave room for load/teardown.
    OVERHEAD_S = 60.0

    def __init__(self, client: McpClient) -> None:
        self.client = client

    async def run_once(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Counts the run (SPEC 18.3) whoever asked: the REST API or an agent."""
        profile = str(spec.get("profile", "fast"))
        try:
            result = await self._run_once(spec)
        except BaseException:
            SIM_RUNS.labels(profile=profile, outcome="error").inc()
            raise
        SIM_RUNS.labels(profile=profile, outcome=str(result.get("outcome", "unknown"))).inc()
        return result

    async def _run_once(self, spec: dict[str, Any]) -> dict[str, Any]:
        """set_seed -> load_world -> run_until -> teardown. No unbounded call.

        The `visual` profile takes the GPU mutex inside neml-mcp-sim itself
        (SPEC 4.5), which is why nothing here touches gpu_lock.
        """
        seed = int(spec["seed"])
        profile = str(spec.get("profile", "fast"))
        duration_s = float(spec.get("duration_s", 60.0))
        budget_s = duration_s + self.OVERHEAD_S
        await self.client.call("sim", "set_seed", {"seed": seed}, timeout_s=budget_s)
        physics = spec.get("physics")
        world_args: dict[str, Any] = {
            "world_id": spec["world_id"],
            "seed": seed,
            "profile": profile,
        }
        if physics:
            world_args["physics"] = physics
        world = await self.client.call("sim", "load_world", world_args, timeout_s=budget_s)
        try:
            result = await self.client.call(
                "sim",
                "run_until",
                {"condition": f"sim_time_s>={duration_s}", "timeout_s": duration_s},
                timeout_s=budget_s,
            )
        finally:
            # Teardown even on failure: a live world holds the GPU and the port.
            await self.client.call("sim", "teardown", {"handle": world}, timeout_s=budget_s)
        return {
            "world_id": spec["world_id"],
            "seed": seed,
            "profile": profile,
            "outcome": "success" if result.get("satisfied") else "timeout",
            "metrics": {"sim_time_s": result.get("sim_time_s")},
            "sim_version": world.get("world_sha256"),
            "physics": physics,
        }


class Llm:
    """SPEC 4.7 provider, plus the liveness probe /health needs."""

    def __init__(self, provider: LLMProvider, base_url: str, model: str) -> None:
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def classify(self, prompt: str, choices: list[str]) -> str:
        return await self.provider.classify(prompt, choices)

    async def fill(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        return await self.provider.fill(prompt, schema)

    async def summarize(self, prompt: str, max_tokens: int) -> str:
        return await self.provider.summarize(prompt, max_tokens)

    async def ping(self) -> str:
        """T-005 — /v1/models answers. Raising is how /health reports `down`."""
        async with httpx.AsyncClient(timeout=5.0) as http:
            response = await http.get(f"{self.base_url}/models")
            response.raise_for_status()
        return self.model


class Bridge:
    """SPEC 9.5 cloud link. Owns the connect-forever task, not the protocol."""

    def __init__(self, cloud: CloudBridge, outbox: Outbox) -> None:
        self.cloud = cloud
        self.outbox = outbox
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self.cloud.run(stop=self._stop))

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self.outbox.close()

    async def health(self) -> dict[str, Any]:
        return {"connected": self.cloud.online, "queued": self.outbox.pending()}

    async def publish(self, snapshot: dict[str, Any]) -> None:
        """SPEC 8.4 PERSIST -> bridge. Queued locally; drains on reconnect."""
        self.cloud.send("event", {"kind": "flow", "state": snapshot})


class Gpu:
    """SPEC 4.5 mutex, in the shape api/runtime.py reports it."""

    def __init__(self, lock: GpuLock) -> None:
        self.lock = lock

    async def acquire(self, consumer: str, timeout_s: float = 300.0) -> float:
        # The manual /stop route must actually stop vLLM before yielding the GPU.
        return await self.lock.acquire(consumer, timeout_s, profile="visual")

    async def release(self, consumer: str) -> bool:
        """False, not an exception: releasing a lock you do not hold is a 409."""
        try:
            await self.lock.release(consumer)
        except RuntimeError:
            return False
        return True


class Orchestrator:
    """`app.state.orchestrator` — POST /v1/command into the SPEC 8.4 graph.

    The PostgreSQL checkpointer is opened on the first command, not at startup:
    SPEC 8.3 gives /health a `down` state for the database, so the process has
    to boot and report that rather than refuse to start.
    """

    def __init__(self, deps: Deps, db_url: str) -> None:
        self._deps = deps
        # SPEC 8.1 drives the ORM with asyncpg; the checkpointer is psycopg.
        self._dsn = db_url.replace("+asyncpg", "")
        self._stack = AsyncExitStack()
        self._graph: Any = None
        self._building = asyncio.Lock()

    async def _graph_once(self) -> Any:
        async with self._building:
            if self._graph is None:
                saver = await self._stack.enter_async_context(
                    graph_module.postgres_checkpointer(self._dsn)
                )
                await saver.setup()
                self._graph = graph_module.build_graph(self._deps, saver)
        return self._graph

    async def handle_command(
        self,
        *,
        text: str,
        actor: str,
        robot_id: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """`text` is untrusted (SPEC 5.4); the graph's nodes wrap it before any
        prompt sees it. Nothing here builds a prompt."""
        thread_id = correlation_id or f"cmd-{time.time_ns():x}"
        graph = await self._graph_once()
        state = await graph.ainvoke(
            {"command": text, "actor": actor, "thread_id": thread_id},
            graph_module.run_config(thread_id),
        )
        return self._summary(state, thread_id, robot_id)

    async def resume(self, *, thread_id: str, decision: dict[str, Any]) -> dict[str, Any]:
        """Continue a flow parked at the SPEC 5.2 approval gate with the human's answer.

        The checkpoint holds the interrupt; the answer becomes the node's `approval`, and the
        execute node then runs (approved) or reports why it did not (rejected / expired).
        """
        graph = await self._graph_once()
        state = await graph.ainvoke(Command(resume=decision), graph_module.run_config(thread_id))
        return self._summary(state, thread_id, None)

    @staticmethod
    def _summary(state: Any, thread_id: str, robot_id: str | None) -> dict[str, Any]:
        final: dict[str, Any] = state if isinstance(state, dict) else state.model_dump(mode="json")
        return {
            "thread_id": thread_id,
            "robot_id": robot_id,
            "intent": final.get("intent"),
            "branch": final.get("branch"),
            "approval_id": final.get("approval_id"),
            "result": final.get("result"),
            "accepted": True,
        }

    async def aclose(self) -> None:
        await self._stack.aclose()


async def bridge_message_logged(envelope: Envelope) -> None:
    """Server -> lab messages. T-055 (Faz 3) turns these into queued commands."""
    log.info("bridge_message", message_type=envelope.type, seq=envelope.seq)
