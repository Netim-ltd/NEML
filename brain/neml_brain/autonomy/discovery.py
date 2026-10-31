# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Task discovery - the five sources and the priority formula (SPEC 14.2)."""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

# --- SPEC 14.2 triggers ---------------------------------------------------
SUCCESS_FLOOR = 0.70  # failure repair: below 70 % over the last 20 runs
RECENT_RUNS = 20
STALENESS_DAYS = 14  # coverage gap: never tried, or older than 14 days
CALIBRATION_MAX_DAYS = 7  # maintenance: more than 7 days since calibration
REALITY_GAP_MAX = 0.15  # maintenance: gap above 0.15
DEADLINE_HORIZON_H = 24.0  # urgency ramp for a human task that carries a deadline

# The formula below is spec'd, the per-source factor estimates are not. These are
# the priors; autonomy/tuning.py refits them from judged task_runs and the result
# arrives here as a `Factors` (ADR-014). With no history the priors are used.
PRIOR_GAIN = {"exploration": 0.30, "evolution": 0.50, "maintenance": 0.40, "calibration": 0.40}
PRIOR_CHEAP = {
    "repair": 0.80,
    "exploration": 0.90,
    "evolution": 0.60,
    "maintenance": 0.50,
    "calibration": 0.50,
}


@dataclass(slots=True, frozen=True)
class Factors:
    gain: dict[str, float] = dataclasses.field(default_factory=lambda: dict(PRIOR_GAIN))
    cheap: dict[str, float] = dataclasses.field(default_factory=lambda: dict(PRIOR_CHEAP))

    def g(self, kind: str) -> float:
        return self.gain.get(kind, PRIOR_GAIN.get(kind, 0.3))

    def c(self, kind: str) -> float:
        return self.cheap.get(kind, PRIOR_CHEAP.get(kind, 0.5))


DEFAULT_FACTORS = Factors()


def clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def priority(
    *,
    is_human: bool = False,
    urgency: float = 0.0,
    expected_gain: float = 0.0,
    staleness: float = 0.0,
    cheapness: float = 0.0,
    blocked: bool = False,
) -> float:
    """SPEC 14.2 priority formula, verbatim.

    P = 100*is_human + 40*urgency + 25*expected_gain + 15*staleness
        + 10*cheapness - 50*blocked
    """
    p = (
        100.0 * is_human
        + 40.0 * clamp01(urgency)
        + 25.0 * clamp01(expected_gain)
        + 15.0 * clamp01(staleness)
        + 10.0 * clamp01(cheapness)
        - 50.0 * blocked
    )
    return round(p, 3)  # tasks.priority is NUMERIC(6,3)


def staleness_of(last_at: datetime | None, now: datetime) -> float:
    """Time since the last attempt / 14 days, clipped. Never tried is fully stale."""
    if last_at is None:
        return 1.0
    return clamp01((now - last_at).total_seconds() / (STALENESS_DAYS * 86400.0))


def deadline_urgency(deadline: datetime | None, now: datetime) -> float:
    if deadline is None:
        return 0.0
    hours_left = (deadline - now).total_seconds() / 3600.0
    return clamp01(1.0 - hours_left / DEADLINE_HORIZON_H)


# --- facts the repository supplies ---------------------------------------
@dataclass(slots=True, frozen=True)
class SkillStats:
    """Aggregate over a skill's last RECENT_RUNS runs."""

    skill_key: str
    runs: int
    successes: int
    last_run_at: datetime | None = None

    @property
    def success_rate(self) -> float:
        return self.successes / self.runs if self.runs else 1.0


@dataclass(slots=True, frozen=True)
class CoverageCell:
    world_id: str
    precondition_key: str
    last_tried_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class RobotHealth:
    robot_id: str
    calibrated_at: datetime | None = None
    reality_gap: float | None = None
    mtbf_below_threshold: bool = False
    # per-model limits from the admin screen (catalog.effective); the SPEC 14.2
    # numbers are the fallback when the owner has not set them
    calibration_max_days: float = CALIBRATION_MAX_DAYS
    gap_max: float = REALITY_GAP_MAX


@dataclass(slots=True, frozen=True)
class HumanCommand:
    command_id: str
    title: str
    spec: dict[str, Any]
    created_at: datetime
    deadline: datetime | None = None
    robot_id: str | None = None
    blocked: bool = False


@dataclass(slots=True, frozen=True)
class TaskProposal:
    """A row-to-be in `tasks` (SPEC 7)."""

    title: str
    kind: str
    source: str
    priority: float
    spec: dict[str, Any]
    dedupe_key: str
    created_at: datetime
    robot_id: str | None = None
    deadline: datetime | None = None


class DiscoveryRepo(Protocol):
    """Read/write surface owned by neml_brain.db."""

    async def skill_stats(self, limit: int = RECENT_RUNS) -> Sequence[SkillStats]: ...
    async def coverage_cells(self) -> Sequence[CoverageCell]: ...
    async def robot_health(self) -> Sequence[RobotHealth]: ...
    async def pending_human_commands(self) -> Sequence[HumanCommand]: ...
    async def open_task_keys(self) -> set[str]: ...
    async def create_task(self, proposal: TaskProposal) -> str: ...


# --- the five sources -----------------------------------------------------
def from_failures(
    stats: Sequence[SkillStats], now: datetime, factors: Factors = DEFAULT_FACTORS
) -> list[TaskProposal]:
    """Success below 70 % over the last 20 runs: targeted parameter search."""
    out = []
    for s in stats:
        if s.runs == 0 or s.success_rate >= SUCCESS_FLOOR:
            continue
        out.append(
            TaskProposal(
                title=f"repair {s.skill_key}",
                kind="repair",
                source="auto:failure",
                priority=priority(
                    expected_gain=(SUCCESS_FLOOR - s.success_rate) / SUCCESS_FLOOR,
                    staleness=staleness_of(s.last_run_at, now),
                    cheapness=factors.c("repair"),
                ),
                spec={"skill_key": s.skill_key, "success_rate": s.success_rate, "runs": s.runs},
                dedupe_key=f"repair:{s.skill_key}",
                created_at=now,
            )
        )
    return out


def from_coverage(
    cells: Sequence[CoverageCell], now: datetime, factors: Factors = DEFAULT_FACTORS
) -> list[TaskProposal]:
    """World/precondition combo never tried, or not tried for over 14 days."""
    cutoff = now - timedelta(days=STALENESS_DAYS)
    out = []
    for c in cells:
        if c.last_tried_at is not None and c.last_tried_at > cutoff:
            continue
        out.append(
            TaskProposal(
                title=f"explore {c.world_id}/{c.precondition_key}",
                kind="exploration",
                source="auto:coverage",
                priority=priority(
                    expected_gain=factors.g("exploration"),
                    staleness=staleness_of(c.last_tried_at, now),
                    cheapness=factors.c("exploration"),
                ),
                spec={"world_id": c.world_id, "precondition_key": c.precondition_key},
                dedupe_key=f"exploration:{c.world_id}:{c.precondition_key}",
                created_at=now,
            )
        )
    return out


def from_maintenance(
    robots: Sequence[RobotHealth], now: datetime, factors: Factors = DEFAULT_FACTORS
) -> list[TaskProposal]:
    """Calibration too old, gap too high, or MTBF under the model's threshold."""
    out = []
    for r in robots:
        stale_cal = now - timedelta(days=r.calibration_max_days)
        gap_bad = r.reality_gap is not None and r.reality_gap > r.gap_max
        cal_bad = r.calibrated_at is None or r.calibrated_at < stale_cal
        if not (gap_bad or cal_bad or r.mtbf_below_threshold):
            continue
        # gap and MTBF point at hardware; a stale clock alone is only calibration
        kind = "maintenance" if (gap_bad or r.mtbf_below_threshold) else "calibration"
        out.append(
            TaskProposal(
                title=f"{kind} {r.robot_id}",
                kind=kind,
                source="auto:maintenance",
                priority=priority(
                    urgency=1.0 if (gap_bad or r.mtbf_below_threshold) else 0.5,
                    expected_gain=factors.g(kind),
                    staleness=staleness_of(r.calibrated_at, now),
                    cheapness=factors.c(kind),
                ),
                spec={
                    "robot_id": r.robot_id,
                    "reality_gap": r.reality_gap,
                    "mtbf_below_threshold": r.mtbf_below_threshold,
                },
                dedupe_key=f"{kind}:{r.robot_id}",
                created_at=now,
                robot_id=r.robot_id,
            )
        )
    return out


def from_human(commands: Sequence[HumanCommand], now: datetime) -> list[TaskProposal]:
    """Mobile/web command - always the highest priority (SPEC 14.2)."""
    return [
        TaskProposal(
            title=c.title,
            kind="human",
            source=f"user:{c.command_id}",
            priority=priority(
                is_human=True,
                urgency=deadline_urgency(c.deadline, now),
                cheapness=1.0,
                blocked=c.blocked,
            ),
            spec=c.spec,
            dedupe_key=f"human:{c.command_id}",
            created_at=c.created_at,
            robot_id=c.robot_id,
            deadline=c.deadline,
        )
        for c in commands
    ]


def order_queue(proposals: Sequence[TaskProposal]) -> list[TaskProposal]:
    """SPEC 14.2: P DESC, ties broken by created_at ASC."""
    return sorted(proposals, key=lambda t: (-t.priority, t.created_at))


async def discover_tasks(
    repo: DiscoveryRepo, now: datetime | None = None, factors: Factors = DEFAULT_FACTORS
) -> list[TaskProposal]:
    """Run all five sources, drop what is already queued, insert in queue order."""
    now = now or datetime.now(UTC)
    proposals = (
        from_human(await repo.pending_human_commands(), now)
        + from_failures(await repo.skill_stats(), now, factors)
        + from_coverage(await repo.coverage_cells(), now, factors)
        + from_maintenance(await repo.robot_health(), now, factors)
    )
    known = await repo.open_task_keys()
    fresh = order_queue([p for p in proposals if p.dedupe_key not in known])
    for p in fresh:
        await repo.create_task(p)
    return fresh


def repair_proposal(
    skill_key: str, success_rate: float, now: datetime, tag: str | None = None
) -> TaskProposal:
    """One repair task. SPEC 14.6 step 5 reuses the SPEC 14.2 failure source."""
    # int() not round(): rounding 0.69 back up to 0.70 would empty the list below
    stats = SkillStats(skill_key, RECENT_RUNS, int(success_rate * RECENT_RUNS), now)
    proposal = from_failures([stats], now)[0]
    if tag is None:
        return proposal
    return dataclasses.replace(proposal, spec={**proposal.spec, "failure_tag": tag})
