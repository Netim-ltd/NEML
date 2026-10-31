# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""PostgreSQL side of the autonomy loop: discovery facts, queue, verdicts, tuning.

Plain SQL on purpose. Every statement is one round trip and reads like the
SPEC 7 column it touches, so it can be checked against the schema by eye.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from neml_brain.settings import catalog
from neml_brain.settings.store import SettingsStore

from .discovery import (
    PRIOR_CHEAP,
    PRIOR_GAIN,
    CoverageCell,
    Factors,
    HumanCommand,
    RobotHealth,
    SkillStats,
    TaskProposal,
)
from .judge import RunFacts, TaskFacts
from .learning import TaskOutcome
from .tuning import RunRecord

# The five worlds under ros2_ws/src/neml_sim/worlds. A cell is (world, "baseline"):
# the world has been driven by any sim run recently, whatever the skill.
WORLDS = ("flat", "maze", "obstacle_low", "ramp_10deg", "rough_terrain")
PHYSICAL_ENVS = ("bench", "tethered", "free")
MTBF_MIN_FAILURES = 2  # one failure is an anecdote, not a rate
OPEN_STATES = ("queued", "planning", "awaiting_approval", "running", "paused")

Sessions = async_sessionmaker[AsyncSession]


class AutonomyRepo:
    """DiscoveryRepo + ReviewRepo + the queue and tuning the service needs."""

    def __init__(self, sessions: Sessions, settings: SettingsStore) -> None:
        self._sessions = sessions
        self._settings = settings

    # ------------------------------------------------------------ discovery
    async def skill_stats(self, limit: int = 20) -> Sequence[SkillStats]:
        sql = sa.text("""
            WITH ranked AS (
                SELECT s.skill_key, sr.success, sr.run_at,
                       row_number() OVER (PARTITION BY s.skill_key
                                          ORDER BY sr.run_at DESC, sr.id DESC) AS rn
                FROM skill_runs sr JOIN skills s ON s.id = sr.skill_id
                WHERE sr.deterministic            -- SPEC 11.2 rule 3
            )
            SELECT skill_key, count(*) AS runs, sum(success::int) AS ok, max(run_at) AS last_at
            FROM ranked WHERE rn <= :n GROUP BY skill_key
        """)
        async with self._sessions() as session:
            rows = (await session.execute(sql, {"n": limit})).all()
        return [SkillStats(r.skill_key, r.runs, int(r.ok), r.last_at) for r in rows]

    async def coverage_cells(self) -> Sequence[CoverageCell]:
        sql = sa.text("SELECT world_id, max(run_at) AS last_at FROM sim_runs GROUP BY world_id")
        async with self._sessions() as session:
            seen = {r.world_id: r.last_at for r in (await session.execute(sql)).all()}
        return [CoverageCell(w, "baseline", seen.get(w)) for w in WORLDS]

    async def robot_health(self) -> Sequence[RobotHealth]:
        robots = sa.text("""
            SELECT r.id, g.name AS model, r.calibrated_at, r.reality_gap::float AS gap
            FROM robots r JOIN genomes g ON g.id = r.genome_id
        """)
        usage = sa.text("""
            SELECT t.robot_id,
                   sum(extract(epoch FROM (tr.ended_at - tr.started_at))) / 3600.0 AS hours,
                   count(*) FILTER (WHERE tr.outcome IN ('failure','aborted','timeout')) AS fails
            FROM task_runs tr JOIN tasks t ON t.id = tr.task_id
            WHERE tr.env = ANY(:envs) AND tr.ended_at IS NOT NULL AND t.robot_id IS NOT NULL
            GROUP BY t.robot_id
        """)
        async with self._sessions() as session:
            rows = (await session.execute(robots)).all()
            used = {
                r.robot_id: (float(r.hours or 0), int(r.fails))
                for r in (await session.execute(usage, {"envs": list(PHYSICAL_ENVS)})).all()
            }
        out = []
        cache: dict[str, dict[str, float | None]] = {}
        for r in rows:
            if r.model not in cache:
                cache[r.model] = catalog.effective(r.model, await self._settings.get(r.model))
            eff = cache[r.model]
            hours, fails = used.get(r.id, (0.0, 0))
            floor = eff["mtbf_min_hours"]  # None until the owner enters it: no decision made
            below = bool(floor and fails >= MTBF_MIN_FAILURES and hours / fails < floor)
            out.append(
                RobotHealth(
                    r.id,
                    r.calibrated_at,
                    r.gap,
                    below,
                    float(eff["calibration_max_days"] or 7),
                    float(eff["reality_gap_max"] or 0.15),
                )
            )
        return out

    async def pending_human_commands(self) -> Sequence[HumanCommand]:
        """Human tasks are inserted straight into `tasks` by the API (state queued),
        so there is nothing to convert here."""
        return []

    async def answered_commands(self) -> list[dict[str, Any]]:
        """Human tasks parked at the approval gate whose approval has since been decided."""
        sql = sa.text("""
            SELECT t.id::text AS task_id, t.result->'command'->>'thread_id' AS thread_id,
                   a.decision, a.decided_by, a.note, a.id::text AS approval_id
            FROM tasks t
            JOIN approvals a ON a.id = CAST(t.result->'command'->>'approval_id' AS uuid)
            WHERE t.kind = 'human' AND t.state = 'awaiting_approval' AND a.decision IS NOT NULL
        """)
        async with self._sessions() as session:
            return [dict(r) for r in (await session.execute(sql)).mappings()]

    async def open_task_keys(self) -> set[str]:
        sql = sa.text(
            "SELECT spec->>'dedupe_key' FROM tasks"
            " WHERE state = ANY(:open) AND spec->>'dedupe_key' IS NOT NULL"
        )
        async with self._sessions() as session:
            return {r[0] for r in (await session.execute(sql, {"open": list(OPEN_STATES)})).all()}

    async def create_task(self, proposal: TaskProposal) -> str:
        sql = sa.text("""
            INSERT INTO tasks (title, kind, source, priority, state, robot_id, spec, deadline)
            VALUES (:title, :kind, :source, :priority, 'queued', :robot, CAST(:spec AS jsonb),
                    :deadline)
            RETURNING id::text
        """)
        spec = {**proposal.spec, "dedupe_key": proposal.dedupe_key}
        async with self._sessions() as session:
            task_id: str = (
                await session.execute(
                    sql,
                    {
                        "title": proposal.title[:200],
                        "kind": proposal.kind,
                        "source": proposal.source,
                        "priority": proposal.priority,
                        "robot": proposal.robot_id,
                        "spec": json.dumps(spec),
                        "deadline": proposal.deadline,
                    },
                )
            ).scalar_one()
            await session.commit()
        return task_id

    # ---------------------------------------------------------------- queue
    async def claim_next_task(self) -> dict[str, Any] | None:
        """SPEC 14.1 pick_next_task, atomically: two loops can never take one task."""
        sql = sa.text("""
            UPDATE tasks SET state = 'running', updated_at = now()
            WHERE id = (SELECT id FROM tasks WHERE state = 'queued'
                        ORDER BY priority DESC, created_at ASC
                        FOR UPDATE SKIP LOCKED LIMIT 1)
            RETURNING id::text AS id, title, kind, spec, robot_id
        """)
        async with self._sessions() as session:
            row = (await session.execute(sql)).mappings().first()
            await session.commit()
        return None if row is None else dict(row)

    async def set_state(
        self, task_id: str, state: str, result: dict[str, Any] | None = None
    ) -> None:
        sql = sa.text(
            "UPDATE tasks SET state = :s, result = coalesce(CAST(:r AS jsonb), result),"
            " updated_at = now() WHERE id = CAST(:id AS uuid)"
        )
        async with self._sessions() as session:
            await session.execute(
                sql,
                {"s": state, "r": None if result is None else json.dumps(result), "id": task_id},
            )
            await session.commit()

    async def release_running(self) -> int:
        """A task still `running` at service start was cut off by a restart: queue it again."""
        sql = sa.text(
            "UPDATE tasks SET state = 'queued', updated_at = now() WHERE state = 'running'"
        )
        async with self._sessions() as session:
            released = cast("CursorResult[Any]", await session.execute(sql)).rowcount
            await session.commit()
        return int(released)

    async def requeue(self, task_id: str, spec: dict[str, Any]) -> None:
        """Retry: same task, adjusted spec, back in the queue."""
        sql = sa.text(
            "UPDATE tasks SET state = 'queued', spec = CAST(:spec AS jsonb), updated_at = now()"
            " WHERE id = CAST(:id AS uuid)"
        )
        async with self._sessions() as session:
            await session.execute(sql, {"spec": json.dumps(spec), "id": task_id})
            await session.commit()

    async def attempts(self, task_id: str) -> int:
        sql = sa.text("SELECT count(*) FROM task_runs WHERE task_id = CAST(:id AS uuid)")
        async with self._sessions() as session:
            return int((await session.execute(sql, {"id": task_id})).scalar_one())

    async def record_run(self, o: TaskOutcome) -> int:
        sql = sa.text("""
            INSERT INTO task_runs (task_id, attempt, env, seed, started_at, ended_at, outcome,
                                   metrics, rosbag_path)
            VALUES (CAST(:id AS uuid), :attempt, :env, :seed, :s, :e, :outcome,
                    CAST(:metrics AS jsonb), :bag)
            RETURNING id
        """)
        async with self._sessions() as session:
            run_id: int = (
                await session.execute(
                    sql,
                    {
                        "id": o.task_id,
                        "attempt": o.attempt,
                        "env": o.env,
                        "seed": o.seed,
                        "s": o.started_at,
                        "e": o.ended_at,
                        "outcome": o.outcome,
                        "metrics": json.dumps(o.metrics, default=str),
                        "bag": o.rosbag_path,
                    },
                )
            ).scalar_one()
            await session.commit()
        return run_id

    async def save_verdict(
        self, run_id: int, done: bool, reasons: Sequence[str], action: str
    ) -> None:
        sql = sa.text("""
            INSERT INTO task_verdicts (task_run_id, done, reasons, action)
            VALUES (:run, :done, CAST(:reasons AS jsonb), :action)
            ON CONFLICT (task_run_id) DO UPDATE
              SET done = EXCLUDED.done, reasons = EXCLUDED.reasons, action = EXCLUDED.action,
                  judged_at = now()
        """)
        async with self._sessions() as session:
            await session.execute(
                sql,
                {
                    "run": run_id,
                    "done": done,
                    "reasons": json.dumps(list(reasons)),
                    "action": action,
                },
            )
            await session.commit()

    async def robot_batteries(self) -> dict[str, float]:
        sql = sa.text("SELECT id, battery_soc::float FROM robots WHERE battery_soc IS NOT NULL")
        async with self._sessions() as session:
            return {r[0]: r[1] for r in (await session.execute(sql)).all()}

    # --------------------------------------------------------------- review
    async def recent_done(self, days: int) -> Sequence[tuple[TaskFacts, RunFacts]]:
        sql = sa.text("""
            SELECT DISTINCT ON (t.id) t.id::text AS id, t.kind, t.spec, tr.env, tr.outcome,
                   tr.metrics, (SELECT count(*) FROM task_runs x WHERE x.task_id = t.id) AS n
            FROM tasks t JOIN task_runs tr ON tr.task_id = t.id
            WHERE t.state = 'succeeded' AND t.updated_at > now() - make_interval(days => :d)
            ORDER BY t.id, tr.attempt DESC
        """)
        async with self._sessions() as session:
            rows = (await session.execute(sql, {"d": days})).mappings().all()
        return [
            (
                TaskFacts(r["id"], r["kind"], r["spec"] or {}, int(r["n"])),
                RunFacts(r["outcome"] or "success", r["env"], r["metrics"] or {}),
            )
            for r in rows
        ]

    async def reopen(self, task_id: str, reasons: Sequence[str]) -> None:
        await self.set_state(task_id, "queued", {"reopened": list(reasons)})

    # --------------------------------------------------------------- tuning
    async def load_factors(self) -> Factors:
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    sa.text("SELECT kind, expected_gain, cheapness FROM autonomy_tuning")
                )
            ).all()
        gain, cheap = dict(PRIOR_GAIN), dict(PRIOR_CHEAP)
        for r in rows:
            gain[r.kind], cheap[r.kind] = r.expected_gain, r.cheapness
        return Factors(gain=gain, cheap=cheap)

    async def judged_history(self, days: int = 90) -> list[RunRecord]:
        sql = sa.text("""
            SELECT t.kind, v.done,
                   extract(epoch FROM (tr.ended_at - tr.started_at)) AS secs
            FROM task_verdicts v JOIN task_runs tr ON tr.id = v.task_run_id
            JOIN tasks t ON t.id = tr.task_id
            WHERE tr.ended_at IS NOT NULL AND v.judged_at > now() - make_interval(days => :d)
        """)
        async with self._sessions() as session:
            rows = (await session.execute(sql, {"d": days})).all()
        return [RunRecord(r.kind, r.done, float(r.secs or 0)) for r in rows]

    async def save_factors(self, rows: Sequence[dict[str, Any]]) -> None:
        sql = sa.text("""
            INSERT INTO autonomy_tuning (kind, expected_gain, cheapness, samples, fitted_at)
            VALUES (:kind, :expected_gain, :cheapness, :samples, :now)
            ON CONFLICT (kind) DO UPDATE SET expected_gain = EXCLUDED.expected_gain,
              cheapness = EXCLUDED.cheapness, samples = EXCLUDED.samples,
              fitted_at = EXCLUDED.fitted_at
        """)
        async with self._sessions() as session:
            for row in rows:
                await session.execute(sql, {**row, "now": datetime.now(UTC)})
            await session.commit()
