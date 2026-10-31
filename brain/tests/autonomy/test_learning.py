# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 14.6 - the five post-task learning steps."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from neml_brain.autonomy.discovery import TaskProposal
from neml_brain.autonomy.learning import LearningDeps, TaskOutcome, record_and_learn
from neml_brain.llm.profiles import FAILURE_MODES

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


class Spy:
    def __init__(self, rate: float = 0.9, tag: str = "foot_slip"):
        self.calls: list[str] = []
        self.runs: list[TaskOutcome] = []
        self.tagged: list[str] = []
        self.chunks: list[tuple[str, str, str]] = []
        self.stats: list[tuple[str, bool]] = []
        self.tasks: list[TaskProposal] = []
        self.rate = rate
        self.tag = tag

    async def record_run(self, outcome: TaskOutcome) -> None:
        self.calls.append("record_run")
        self.runs.append(outcome)

    async def tag_failure(self, context: str) -> str:
        self.calls.append("tag_failure")
        self.tagged.append(context)
        return self.tag

    async def remember(self, source_kind: str, source_id: str, content: str) -> None:
        self.calls.append("remember")
        self.chunks.append((source_kind, source_id, content))

    async def update_skill_stats(self, skill_key: str, success: bool) -> float:
        self.calls.append("update_skill_stats")
        self.stats.append((skill_key, success))
        return self.rate

    async def create_task(self, proposal: TaskProposal) -> str:
        self.calls.append("create_task")
        self.tasks.append(proposal)
        return proposal.dedupe_key

    def deps(self) -> LearningDeps:
        return LearningDeps(
            record_run=self.record_run,
            tag_failure=self.tag_failure,
            remember=self.remember,
            update_skill_stats=self.update_skill_stats,
            create_task=self.create_task,
        )


def _outcome(result: str = "failure") -> TaskOutcome:
    return TaskOutcome(
        task_id="t-1",
        attempt=1,
        env="sim",
        started_at=NOW - timedelta(minutes=2),
        ended_at=NOW,
        outcome=result,
        context="leg 3 slipped on the ramp at t=4.2s",
        skill_key="climb",
        seed=42,
    )


async def test_success_records_and_updates_stats_only():
    spy = Spy(rate=0.95)
    tag = await record_and_learn(spy.deps(), _outcome("success"), NOW)
    assert tag is None
    assert spy.calls == ["record_run", "update_skill_stats"]
    assert spy.stats == [("climb", True)]


async def test_failure_walks_all_five_steps_and_queues_a_repair():
    spy = Spy(rate=0.55)
    tag = await record_and_learn(spy.deps(), _outcome(), NOW)
    assert tag == "foot_slip"
    assert spy.calls == [
        "record_run",  # 1
        "tag_failure",  # 2
        "remember",  # 3
        "update_skill_stats",  # 4
        "create_task",  # 5
    ]
    assert spy.tagged == ["leg 3 slipped on the ramp at t=4.2s"]
    kind, source_id, content = spy.chunks[0]
    assert (kind, source_id) == ("failure", "t-1")
    assert content.startswith("[foot_slip] ")
    repair = spy.tasks[0]
    assert repair.kind == "repair"
    assert repair.spec["skill_key"] == "climb"
    assert repair.spec["failure_tag"] == "foot_slip"


async def test_no_repair_while_the_skill_is_at_or_above_seventy_percent():
    spy = Spy(rate=0.70)
    await record_and_learn(spy.deps(), _outcome(), NOW)
    assert "create_task" not in spy.calls


async def test_repair_fires_the_moment_the_rate_slips_under_the_floor():
    spy = Spy(rate=0.699)
    await record_and_learn(spy.deps(), _outcome(), NOW)
    assert spy.tasks and spy.tasks[0].kind == "repair"


async def test_a_success_can_also_drag_the_rate_under_the_floor():
    """Step 5 keys off the cumulative rate, not off this one run."""
    spy = Spy(rate=0.4)
    await record_and_learn(spy.deps(), _outcome("success"), NOW)
    assert spy.calls == ["record_run", "update_skill_stats", "create_task"]
    assert spy.tasks[0].spec.get("failure_tag") is None


async def test_a_task_without_a_skill_still_gets_recorded_and_tagged():
    spy = Spy()
    outcome = _outcome()
    outcome.skill_key = None
    tag = await record_and_learn(spy.deps(), outcome, NOW)
    assert tag == "foot_slip"
    assert spy.calls == ["record_run", "tag_failure", "remember"]


async def test_timeout_and_abort_count_as_failures():
    for result in ("timeout", "aborted"):
        spy = Spy(rate=0.9)
        await record_and_learn(spy.deps(), _outcome(result), NOW)
        assert "tag_failure" in spy.calls
        assert spy.stats == [("climb", False)]


# --- SPEC 14.6 step 2 / owner decision 4: one failure-mode list --------------


@pytest.mark.parametrize("mode", FAILURE_MODES)
async def test_every_failure_mode_is_written_through_as_the_tag(mode):
    """The tag reaches memory_chunks and the repair task unchanged.

    It is also the string skill_runs.failure_mode stores, so these ten values and
    that column's domain are the same set by construction.
    """
    spy = Spy(rate=0.5, tag=mode)
    assert await record_and_learn(spy.deps(), _outcome(), NOW) == mode
    assert spy.chunks[0][2].startswith(f"[{mode}] ")
    assert spy.tasks[0].spec["failure_tag"] == mode


async def test_a_tag_outside_the_list_is_refused_before_it_is_stored():
    spy = Spy(tag="actuator_fault")  # one of the ten reflection.py used to invent
    with pytest.raises(ValueError, match="not a failure_tag mode"):
        await record_and_learn(spy.deps(), _outcome(), NOW)
    assert spy.chunks == [], "nothing is embedded under an unknown tag"


async def test_reflection_and_learning_tag_from_the_same_list():
    """Both import it; neither keeps a copy. The agent produces it, learning stores it."""
    from neml_brain.agents import reflection

    assert reflection.FAILURE_MODES is FAILURE_MODES
    assert reflection.PROFILE == "failure_tag"
