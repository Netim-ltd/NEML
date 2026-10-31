# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The autonomy loop as a service: dependencies, task execution, judging, upkeep.

Safety posture (ADR-014): the loop only ever *simulates*. A task that would move
hardware is parked in `awaiting_approval` behind a level-4 owner approval, and a
task with no autonomous executor is parked as `paused` with the reason. Physical
autonomy is refused at startup; enabling it is a code change guarded by SAFETY.md,
not an environment variable.

Off by default: nothing runs unless NEML_AUTONOMY_ENABLED=true.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import structlog

from neml_brain.llm.profiles import FAILURE_MODES

from .db_repo import AutonomyRepo
from .discovery import (
    DEFAULT_FACTORS,
    Factors,
    discover_tasks,
    from_coverage,
    from_maintenance,
    repair_proposal,
)
from .idle import IdleDeps
from .judge import RunFacts, TaskFacts, judge
from .learning import LearningDeps, TaskOutcome, record_and_learn
from .loop import AutonomyDeps, autonomy_loop
from .review import review_completed
from .tuning import as_rows, fit

log = structlog.get_logger(__name__)

UPKEEP_INTERVAL_S = 24 * 3600  # review + refit, once a day
BUDGET_RETRY_S = 300
SIM_ENV = "sim"
# Every kind below needs a robot, a campaign pipeline or a calibration harness the
# loop does not drive. They are parked, never silently dropped (see park()).
PARKED_KINDS = frozenset({"maintenance", "calibration", "repair"})


class Sim(Protocol):
    async def run_once(self, spec: dict[str, Any]) -> dict[str, Any]: ...


class Orchestrator(Protocol):
    async def handle_command(
        self,
        *,
        text: str,
        actor: str,
        robot_id: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]: ...

    async def resume(self, *, thread_id: str, decision: dict[str, Any]) -> dict[str, Any]: ...


class Evolution(Protocol):
    async def record_run(self, spec: dict[str, Any]) -> dict[str, Any]: ...

    async def publish_scenes(self) -> int: ...


class Budget(Protocol):
    async def allow(self, resource: str) -> bool: ...


@dataclass(slots=True)
class Runtime:
    repo: AutonomyRepo
    sim: Sim
    orchestrator: Orchestrator
    budget: Budget
    create_approval: Callable[..., Awaitable[str]]
    tag_failure: Callable[[str], Awaitable[str]]  # llm failure_tag profile
    remember: Callable[[str, str, str], Awaitable[None]]
    update_skill_stats: Callable[[str, bool], Awaitable[float]]
    consolidate_memory: Callable[[], Awaitable[int]]
    notify: Callable[[dict[str, Any]], Awaitable[None]]  # bridge event to the owner
    factors: Factors = DEFAULT_FACTORS
    evolution: Evolution | None = None  # recorded runs and 3D scenes of the lab


def seed_for(task_id: str, attempt_spec: dict[str, Any]) -> int:
    """Deterministic and traceable (SPEC 11.2): the same task replays the same world."""
    if "seed" in attempt_spec:
        return int(attempt_spec["seed"])
    return int.from_bytes(hashlib.sha256(task_id.encode()).digest()[:4], "big")


class AutonomyService:
    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    # ----------------------------------------------------------- loop deps
    def deps(self) -> AutonomyDeps:
        return AutonomyDeps(
            safety_preflight=self.preflight,
            budget_ok=self.budget_ok,
            sleep_until_budget_reset=self.sleep_until_budget_reset,
            discover_tasks=self.discover,
            pick_next_task=self.rt.repo.claim_next_task,
            idle_policy=self.idle,
            execute=self.execute,
            record_and_learn=self.record,
            on_safety_failure=self.on_safety_failure,
        )

    async def preflight(self) -> None:
        # Sim-only: there is no L0 hardware in the loop to verify. The physical
        # gate (safety.preflight.require_safety_checks) is what any future
        # physical executor must call first.
        return None

    async def on_safety_failure(self, exc: BaseException) -> None:
        await self.rt.notify({"kind": "autonomy_safety_failure", "error": str(exc)})

    async def budget_ok(self) -> bool:
        return await self.rt.budget.allow("sim_runs") and await self.rt.budget.allow("llm_tokens")

    async def sleep_until_budget_reset(self) -> None:
        await asyncio.sleep(BUDGET_RETRY_S)  # the ledger rolls itself at 00:00 TRT

    async def settle_commands(self) -> int:
        """Finish human commands the owner has answered: run them (approved) or close them."""
        answered = await self.rt.repo.answered_commands()
        for item in answered:
            decision = {k: item[k] for k in ("decision", "decided_by", "note")}
            try:
                result = await self.rt.orchestrator.resume(
                    thread_id=item["thread_id"], decision=decision
                )
            except Exception as exc:  # noqa: BLE001 - stays parked, retried on the next tick
                log.error("autonomy.resume_failed", task_id=item["task_id"], error=str(exc))
                continue
            executed = bool((result.get("result") or {}).get("executed"))
            state = "succeeded" if executed else "cancelled"
            await self.rt.repo.set_state(item["task_id"], state, {"resumed": result, **decision})
        return len(answered)

    async def discover(self) -> Any:
        await self.settle_commands()  # apply the owner's answers before picking work
        return await discover_tasks(self.rt.repo, factors=self.rt.factors)

    # ---------------------------------------------------------------- idle
    async def _created(self, proposals: list[Any]) -> bool:
        known = await self.rt.repo.open_task_keys()
        fresh = [p for p in proposals if p.dedupe_key not in known]
        for p in fresh:
            await self.rt.repo.create_task(p)
        return bool(fresh)

    async def idle(self) -> Any:
        from .discovery import TaskProposal
        from .idle import idle_policy

        repo, rt = self.rt.repo, self.rt

        async def charge(robot_id: str) -> None:
            # No motion: a maintenance task is queued, and it is parked for approval
            # like every other task that needs the robot.
            task = TaskProposal(
                f"charge {robot_id}",
                "maintenance",
                "auto:idle",
                60.0,
                {"action": "charge", "robot_id": robot_id},
                f"charge:{robot_id}",
                datetime.now(UTC),
                robot_id=robot_id,
            )
            await self._created([task])

        async def exploration() -> bool:
            cells = await repo.coverage_cells()
            return await self._created(from_coverage(cells, datetime.now(UTC), rt.factors))

        async def calibration() -> bool:
            health = await repo.robot_health()
            due = from_maintenance(health, datetime.now(UTC), rt.factors)
            return await self._created([p for p in due if p.kind == "calibration"])

        return await idle_policy(
            IdleDeps(
                robot_batteries=repo.robot_batteries,
                send_to_charger=charge,
                make_exploration_task=exploration,
                make_calibration_task=calibration,
                consolidate_memory=rt.consolidate_memory,
                budget_ok=self.budget_ok,
            )
        )

    # ------------------------------------------------------------- execute
    async def execute(self, task: dict[str, Any]) -> None:
        """Run one claimed task. The result is left on task["_outcome"] for record()."""
        spec = dict(task["spec"])
        task["_outcome"] = None
        started = datetime.now(UTC)

        if task["kind"] == "human":
            result = await self.rt.orchestrator.handle_command(
                text=str(spec.get("command") or task["title"]),
                actor=f"task:{task['id']}",
                robot_id=task.get("robot_id"),
                correlation_id=f"task-{task['id']}",
            )
            if result.get("approval_id") and not (result.get("result") or {}).get("executed"):
                await self.rt.repo.set_state(task["id"], "awaiting_approval", {"command": result})
                return
            ok = bool(result.get("accepted"))
            task["_outcome"] = self._outcome(task, started, SIM_ENV, ok, {"command": result})
            return

        if spec.get("record") and self.rt.evolution is not None and not task.get("robot_id"):
            recorded = await self.rt.evolution.record_run(spec)
            ok = recorded["outcome"] == "success"
            task["_outcome"] = self._outcome(task, started, SIM_ENV, ok, recorded["metrics"])
            return

        if task["kind"] not in PARKED_KINDS and spec.get("world_id") and not task.get("robot_id"):
            sim = await self.rt.sim.run_once(
                {
                    "world_id": spec["world_id"],
                    "seed": seed_for(task["id"], spec),
                    "profile": "fast",
                    "duration_s": float(spec.get("duration_s", 60.0)),
                }
            )
            ok = sim.get("outcome") == "success"
            metrics = {**(sim.get("metrics") or {}), "sim_version": sim.get("sim_version")}
            task["_outcome"] = self._outcome(task, started, SIM_ENV, ok, metrics)
            return

        await self.park(task)

    def _outcome(
        self, task: dict[str, Any], started: datetime, env: str, ok: bool, metrics: dict[str, Any]
    ) -> TaskOutcome:
        spec = task["spec"]
        return TaskOutcome(
            task_id=task["id"],
            attempt=0,  # filled in by record(), which knows the stored run count
            env=env,
            started_at=started,
            ended_at=datetime.now(UTC),
            outcome="success" if ok else "failure",
            context=str(metrics)[:600],
            skill_key=spec.get("skill_key"),
            seed=seed_for(task["id"], spec),
            metrics=metrics,
        )

    async def park(self, task: dict[str, Any]) -> None:
        """No autonomous executor: say so, keep the task, and ask the owner when a
        robot is involved. Nothing is dropped and nothing is run."""
        reason = f"no autonomous executor for kind '{task['kind']}' (sim-only loop)"
        if task.get("robot_id"):
            approval_id = await self.rt.create_approval(
                level=4,
                subject_kind="task",
                subject_id=task["id"],
                payload={"title": task["title"], "kind": task["kind"], "spec": task["spec"]},
                idempotency_key=f"task:{task['id']}:park",
            )
            await self.rt.repo.set_state(
                task["id"], "awaiting_approval", {"parked": reason, "approval_id": approval_id}
            )
        else:
            await self.rt.repo.set_state(task["id"], "paused", {"parked": reason})
        await self.rt.notify({"kind": "task_parked", "task_id": task["id"], "reason": reason})
        log.info("autonomy.parked", task_id=task["id"], kind=task["kind"])

    # ------------------------------------------------------ record + learn
    async def record(self, task: dict[str, Any]) -> None:
        outcome: TaskOutcome | None = task.get("_outcome")
        if outcome is None:
            return  # parked or waiting on a human: nothing to judge yet
        repo = self.rt.repo
        outcome.attempt = await repo.attempts(task["id"]) + 1
        run_id = await repo.record_run(outcome)

        facts = TaskFacts(
            task["id"], task["kind"], task["spec"], outcome.attempt, outcome.skill_key
        )
        verdict = judge(facts, RunFacts(outcome.outcome, outcome.env, outcome.metrics))
        await repo.save_verdict(run_id, verdict.done, verdict.reasons, verdict.action)

        # Act on the verdict first: a learning failure below must never lose it.
        if verdict.action == "accept":
            shown = ("media", "world_id", "mass_kg", "x_m", "goal_reached", "tipped_over")
            await repo.set_state(
                task["id"],
                "succeeded",
                {"verdict": "accepted", **{k: v for k, v in outcome.metrics.items() if k in shown}},
            )
        elif verdict.action == "retry":
            await repo.requeue(task["id"], dict(verdict.next_spec or {}))
        elif verdict.action == "repair":
            await repo.set_state(
                task["id"], "failed", {"verdict": "repair", "why": verdict.reasons}
            )
            if outcome.skill_key:
                await repo.create_task(repair_proposal(outcome.skill_key, 0.0, datetime.now(UTC)))
        else:
            await repo.set_state(
                task["id"], "failed", {"verdict": "escalated", "why": verdict.reasons}
            )
            await self.rt.notify(
                {"kind": "task_escalated", "task_id": task["id"], "reasons": list(verdict.reasons)}
            )

        if not verdict.done:
            outcome.outcome = "failure"
        try:
            await record_and_learn(
                LearningDeps(
                    record_run=_noop_record,  # already stored above, with its run id
                    tag_failure=self.rt.tag_failure,
                    remember=self.rt.remember,
                    update_skill_stats=self.rt.update_skill_stats,
                    create_task=repo.create_task,
                ),
                outcome,
            )
        except Exception as exc:  # noqa: BLE001 - learning is best effort, the verdict is stored
            log.error("autonomy.learning_failed", task_id=task["id"], error=str(exc))

    # -------------------------------------------------------------- upkeep
    async def upkeep(self) -> dict[str, Any]:
        """Daily: second look at finished work, then refit the priority factors."""
        repo = self.rt.repo
        reopened = await review_completed(repo)
        history = await repo.judged_history()
        factors = fit(history, self.rt.factors)
        counts: dict[str, int] = {}
        for r in history:
            counts[r.kind] = counts.get(r.kind, 0) + 1
        await repo.save_factors(as_rows(factors, counts))
        self.rt.factors = factors
        log.info("autonomy.upkeep", reopened=len(reopened), runs=len(history))
        return {"reopened": reopened, "runs": len(history)}


async def _noop_record(_: TaskOutcome) -> None:
    return None


async def tag_with_llm(llm: Any, context: str) -> str:
    """SPEC 14.6 step 2. Falls back to `unknown`, the listed escape hatch."""
    try:
        tag: str = await llm.classify(context[:1500], FAILURE_MODES, profile="failure_tag")
    except Exception:  # noqa: BLE001
        return "unknown"
    return tag if tag in FAILURE_MODES else "unknown"


def enabled() -> bool:
    return os.getenv("NEML_AUTONOMY_ENABLED", "false").lower() == "true"


def require_sim_only() -> None:
    mode = os.getenv("NEML_AUTONOMY_MODE", "sim_only")
    if mode != "sim_only":
        raise SystemExit(
            f"NEML_AUTONOMY_MODE={mode!r} refused: this build runs the loop in simulation only. "
            "Physical autonomy needs the SAFETY.md gates wired into an executor first."
        )


async def run(service: AutonomyService, stop: asyncio.Event) -> None:
    """The loop plus the daily upkeep, until `stop` is set."""

    async def upkeep_forever() -> None:
        await asyncio.sleep(60)
        while not stop.is_set():
            try:
                await service.upkeep()
            except Exception as exc:  # noqa: BLE001
                log.error("autonomy.upkeep_failed", error=str(exc))
            await asyncio.sleep(UPKEEP_INTERVAL_S)

    if service.rt.evolution is not None:
        try:
            await service.rt.evolution.publish_scenes()  # the panel's 3D models
        except Exception as exc:  # noqa: BLE001
            log.error("autonomy.scenes_failed", error=str(exc))
    released = await service.rt.repo.release_running()
    if released:
        log.warning("autonomy.released_running", tasks=released)  # cut off by the last restart
    upkeep = asyncio.create_task(upkeep_forever())
    try:
        await autonomy_loop(service.deps(), stop=stop)
    finally:
        upkeep.cancel()
