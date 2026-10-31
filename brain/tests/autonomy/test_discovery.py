# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 14.2 - four sources, their exact triggers (T-085)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from neml_brain.autonomy.discovery import (
    CoverageCell,
    HumanCommand,
    RobotHealth,
    SkillStats,
    TaskProposal,
    discover_tasks,
    from_coverage,
    from_failures,
    from_human,
    from_maintenance,
    repair_proposal,
)

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


class FakeRepo:
    def __init__(self, **facts):
        self.facts = facts
        self.created: list[TaskProposal] = []

    async def skill_stats(self, limit: int = 20):
        return self.facts.get("skills", [])

    async def coverage_cells(self):
        return self.facts.get("cells", [])

    async def robot_health(self):
        return self.facts.get("robots", [])

    async def pending_human_commands(self):
        return self.facts.get("commands", [])

    async def open_task_keys(self):
        return self.facts.get("known", set())

    async def create_task(self, proposal: TaskProposal) -> str:
        self.created.append(proposal)
        return proposal.dedupe_key


# --- source 1: failure repair, < 70 % over the last 20 runs ---------------
def test_failure_repair_triggers_below_seventy_percent():
    below = SkillStats("climb", runs=20, successes=13, last_run_at=NOW)  # 0.65
    at_floor = SkillStats("walk", runs=20, successes=14, last_run_at=NOW)  # 0.70
    above = SkillStats("turn", runs=20, successes=19, last_run_at=NOW)
    never_run = SkillStats("new", runs=0, successes=0)
    out = from_failures([below, at_floor, above, never_run], NOW)
    assert [p.spec["skill_key"] for p in out] == ["climb"]
    assert out[0].kind == "repair"
    assert out[0].source == "auto:failure"


# --- source 2: coverage gap, never tried or > 14 days ---------------------
def test_coverage_gap_triggers_on_never_and_on_fourteen_days():
    cells = [
        CoverageCell("flat", "dry", last_tried_at=None),
        CoverageCell("slope", "wet", last_tried_at=NOW - timedelta(days=15)),
        CoverageCell("stairs", "dry", last_tried_at=NOW - timedelta(days=13)),
    ]
    out = from_coverage(cells, NOW)
    assert {p.spec["world_id"] for p in out} == {"flat", "slope"}
    assert all(p.kind == "exploration" for p in out)


# --- source 4: maintenance ------------------------------------------------
def test_maintenance_triggers_on_calibration_gap_and_mtbf():
    robots = [
        RobotHealth("R01", calibrated_at=NOW - timedelta(days=8), reality_gap=0.05),
        RobotHealth("R02", calibrated_at=NOW, reality_gap=0.16),
        RobotHealth("R03", calibrated_at=NOW, reality_gap=0.05, mtbf_below_threshold=True),
        RobotHealth("R04", calibrated_at=NOW - timedelta(days=6), reality_gap=0.15),
    ]
    out = {p.spec["robot_id"]: p for p in from_maintenance(robots, NOW)}
    assert set(out) == {"R01", "R02", "R03"}  # R04 is inside every threshold
    assert out["R01"].kind == "calibration"  # stale clock only
    assert out["R02"].kind == "maintenance"  # reality gap is a hardware fault
    assert out["R03"].kind == "maintenance"
    assert out["R02"].robot_id == "R02"


# --- source 5: human ------------------------------------------------------
def test_human_command_is_always_highest():
    human = from_human(
        [HumanCommand("cmd-1", "walk to the bench", {"kind": "goto"}, created_at=NOW)], NOW
    )[0]
    auto = from_maintenance([RobotHealth("R02", calibrated_at=None, reality_gap=0.99)], NOW)[0]
    assert human.kind == "human"
    assert human.source == "user:cmd-1"
    assert human.priority > auto.priority


# --- all four together ----------------------------------------------------
async def test_every_source_produces_at_least_one_task():
    repo = FakeRepo(
        skills=[SkillStats("climb", 20, 10, NOW)],
        cells=[CoverageCell("flat", "dry")],
        robots=[RobotHealth("R01", calibrated_at=None)],
        commands=[HumanCommand("cmd-1", "estop", {}, created_at=NOW)],
    )
    fresh = await discover_tasks(repo, NOW)
    assert {p.kind for p in fresh} == {
        "repair",
        "exploration",
        "calibration",
        "human",
    }
    assert repo.created == fresh
    assert fresh[0].kind == "human"  # queue comes back in priority order
    assert [p.priority for p in fresh] == sorted((p.priority for p in fresh), reverse=True)


async def test_already_queued_tasks_are_not_duplicated():
    repo = FakeRepo(
        skills=[SkillStats("climb", 20, 10, NOW)],
        known={"repair:climb"},
    )
    assert await discover_tasks(repo, NOW) == []
    assert repo.created == []


def test_repair_proposal_carries_the_failure_tag():
    p = repair_proposal("climb", 0.69, NOW, tag="foot_slip")
    assert p.kind == "repair"
    assert p.dedupe_key == "repair:climb"
    assert p.spec["failure_tag"] == "foot_slip"
    assert repair_proposal("climb", 0.1, NOW).spec.get("failure_tag") is None
