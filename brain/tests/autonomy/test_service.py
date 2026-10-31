# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""AutonomyService against fakes: execute -> record -> judge -> act, and the parking rules."""

from typing import Any

import pytest

from neml_brain.autonomy import service
from neml_brain.autonomy.service import AutonomyService, Runtime


class FakeRepo:
    def __init__(self, attempts: int = 0) -> None:
        self.n = attempts
        self.states: dict[str, tuple[str, Any]] = {}
        self.runs: list[Any] = []
        self.verdicts: list[tuple[bool, list[str], str]] = []
        self.requeued: list[tuple[str, dict[str, Any]]] = []
        self.created: list[Any] = []
        self.saved: list[Any] = []
        self.answered: list[dict[str, Any]] = []

    async def claim_next_task(self) -> None:
        return None

    async def release_running(self) -> int:
        return 0

    async def answered_commands(self) -> list[dict[str, Any]]:
        return self.answered

    async def set_state(self, task_id: str, state: str, result: Any = None) -> None:
        self.states[task_id] = (state, result)

    async def attempts(self, task_id: str) -> int:
        return self.n

    async def record_run(self, outcome: Any) -> int:
        self.runs.append(outcome)
        return len(self.runs)

    async def save_verdict(self, run_id: int, done: bool, reasons: Any, action: str) -> None:
        self.verdicts.append((done, list(reasons), action))

    async def requeue(self, task_id: str, spec: dict[str, Any]) -> None:
        self.requeued.append((task_id, spec))

    async def create_task(self, proposal: Any) -> str:
        self.created.append(proposal)
        return "new"

    async def judged_history(self) -> list[Any]:
        return []

    async def save_factors(self, rows: Any) -> None:
        self.saved.append(rows)

    async def recent_done(self, days: int) -> list[Any]:
        return []


class FakeSim:
    def __init__(self, outcome: str = "success") -> None:
        self.outcome, self.specs = outcome, []

    async def run_once(self, spec: dict[str, Any]) -> dict[str, Any]:
        self.specs.append(spec)
        return {"outcome": self.outcome, "metrics": {"sim_time_s": 60.0}, "sim_version": "abc"}


class FakeOrch:
    async def handle_command(self, **kw: Any) -> dict[str, Any]:
        return {"accepted": True, "approval_id": None, "result": {"rows": []}}


class Budget:
    async def allow(self, resource: str) -> bool:
        return True


def build(repo: FakeRepo, sim: FakeSim | None = None) -> tuple[AutonomyService, list[Any]]:
    approvals: list[dict[str, Any]] = []
    notes: list[Any] = []

    async def create_approval(**kw: Any) -> str:
        approvals.append(kw)
        return "apr-1"

    async def tag(_: str) -> str:
        return "unknown"

    async def remember(*_: str) -> None:
        return None

    async def stats(_: str, __: bool) -> float:
        return 1.0

    async def consolidate() -> int:
        return 0

    async def notify(event: dict[str, Any]) -> None:
        notes.append(event)

    rt = Runtime(
        repo=repo,  # type: ignore[arg-type]
        sim=sim or FakeSim(),
        orchestrator=FakeOrch(),
        budget=Budget(),
        create_approval=create_approval,
        tag_failure=tag,
        remember=remember,
        update_skill_stats=stats,
        consolidate_memory=consolidate,
        notify=notify,
    )
    svc = AutonomyService(rt)
    svc.approvals, svc.notes = approvals, notes  # type: ignore[attr-defined]
    return svc, notes


def sim_task(kind: str = "exploration", **spec: Any) -> dict[str, Any]:
    return {
        "id": "t1",
        "title": "x",
        "kind": kind,
        "spec": {"world_id": "flat", **spec},
        "robot_id": None,
    }


async def test_a_successful_sim_task_is_judged_done_and_marked_succeeded() -> None:
    repo = FakeRepo()
    svc, _ = build(repo)
    task = sim_task()
    await svc.execute(task)
    await svc.record(task)
    assert repo.runs[0].attempt == 1 and repo.runs[0].env == "sim"
    assert repo.verdicts == [(True, [], "accept")]
    assert repo.states["t1"][0] == "succeeded"


async def test_a_failed_run_is_retried_with_the_next_seed() -> None:
    repo = FakeRepo(attempts=0)
    svc, _ = build(repo, FakeSim("timeout"))
    task = sim_task(seed=7)
    await svc.execute(task)
    await svc.record(task)
    assert repo.verdicts[0][2] == "retry"
    assert repo.requeued[0][1]["seed"] == 8  # judged spec seed + 1, never the same world twice


async def test_attempts_run_out_into_an_escalation_with_a_notification() -> None:
    repo = FakeRepo(attempts=5)
    svc, notes = build(repo, FakeSim("timeout"))
    task = sim_task()
    await svc.execute(task)
    await svc.record(task)
    assert repo.verdicts[0][2] == "escalate"
    assert repo.states["t1"][0] == "failed"
    assert notes[0]["kind"] == "task_escalated"


@pytest.mark.parametrize("kind", ["maintenance", "calibration", "repair"])
async def test_kinds_without_an_executor_are_parked_not_run(kind: str) -> None:
    repo, sim = FakeRepo(), FakeSim()
    svc, notes = build(repo, sim)
    task = sim_task(kind)
    await svc.execute(task)
    await svc.record(task)
    assert sim.specs == [] and repo.runs == []
    assert repo.states["t1"][0] == "paused"
    assert notes[0]["kind"] == "task_parked"


async def test_a_robot_task_needs_a_level_four_owner_approval() -> None:
    repo = FakeRepo()
    svc, _ = build(repo)
    task = {**sim_task("maintenance"), "robot_id": "R01"}
    await svc.execute(task)
    assert repo.states["t1"][0] == "awaiting_approval"
    assert svc.approvals[0]["level"] == 4  # type: ignore[attr-defined]


async def test_a_robot_task_never_reaches_the_simulator_even_with_a_world() -> None:
    repo, sim = FakeRepo(), FakeSim()
    svc, _ = build(repo, sim)
    task = {**sim_task("exploration"), "robot_id": "R01"}
    await svc.execute(task)
    assert sim.specs == [] and repo.states["t1"][0] == "awaiting_approval"


async def test_upkeep_refits_and_stores_the_factors() -> None:
    repo = FakeRepo()
    svc, _ = build(repo)
    out = await svc.upkeep()
    assert out == {"reopened": [], "runs": 0}
    assert repo.saved and {r["kind"] for r in repo.saved[0]} >= {"exploration", "evolution"}


def test_physical_mode_is_refused_and_the_service_is_off_by_default(monkeypatch: Any) -> None:
    monkeypatch.delenv("NEML_AUTONOMY_ENABLED", raising=False)
    assert service.enabled() is False
    monkeypatch.setenv("NEML_AUTONOMY_MODE", "physical")
    with pytest.raises(SystemExit, match="simulation only"):
        service.require_sim_only()


def test_the_seed_is_deterministic_per_task() -> None:
    assert service.seed_for("abc", {}) == service.seed_for("abc", {})
    assert service.seed_for("abc", {"seed": 5}) == 5


async def test_an_approved_command_is_resumed_and_a_rejected_one_is_closed() -> None:
    repo = FakeRepo()
    repo.answered = [
        {
            "task_id": "a",
            "thread_id": "task-a",
            "decision": "approved",
            "decided_by": "o",
            "note": None,
        },
        {
            "task_id": "b",
            "thread_id": "task-b",
            "decision": "rejected",
            "decided_by": "o",
            "note": None,
        },
    ]
    svc, _ = build(repo)
    resumed: list[str] = []

    async def resume(*, thread_id: str, decision: dict[str, Any]) -> dict[str, Any]:
        resumed.append(thread_id)
        return {"result": {"executed": decision["decision"] == "approved"}}

    svc.rt.orchestrator.resume = resume  # type: ignore[attr-defined]
    assert await svc.settle_commands() == 2
    assert resumed == ["task-a", "task-b"]
    assert repo.states["a"][0] == "succeeded" and repo.states["b"][0] == "cancelled"
