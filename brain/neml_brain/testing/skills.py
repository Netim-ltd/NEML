# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 14.3 acceptance condition 3 as a test gate: no validated skill may regress (T-038).

`pytest -m regression` (SPEC 18.1 "Sim regresyon / Tum validated skill", CI gate 7)
judges every skill whose `skills.status` is 'validated' against its own recorded
`skill_validations` rows: the rate of the oldest usable row is the baseline the skill
was validated at, the newest usable row is the replay, and a drop of more than
MAX_REGRESSION (SPEC 14.3: "hala >= eski basari - %5") fails the suite.

The skill set is data, never a list in a test file, so a skill is covered the day it is
marked validated. Where the data comes from is injected through `SkillSource`:
`DbSkillSource` on the lab host, `JsonSkillSource` over a committed corpus everywhere
else, because CI has neither PostgreSQL nor Gazebo. Re-running the trials belongs to the
lab (neml-mcp-sim, SPEC 6.3); that job appends the newest skill_validations row and this
harness is what reads the row and passes or fails on it.

SPEC 11.2 rule 3: a run whose metrics drifted is marked `sim_runs.deterministic = false`
and "evrim kararinda kullanilmaz". Condition 3 is part of that decision, so a validation
carrying such a seed is excluded from the judgement, not counted as a bad result.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
from collections import defaultdict
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

import sqlalchemy as sa

from neml_brain.db.models import SimRun, Skill, SkillValidation
from neml_brain.db.session import get_sessionmaker

MAX_REGRESSION = 0.05  # SPEC 14.3 condition 3: within 5% of the old success rate

# SPEC 14.2 judges a skill over its last 20 runs; below that there is nothing to judge.
MIN_TRIALS = 20

Status = Literal["ok", "regressed", "undecided"]

# SPEC 7: only `sim` validations are replayable in CI, and SPEC 18.1 names this gate
# "Sim regresyon". `real` rows belong to the hardware-in-the-loop row of the pyramid.
SIM_ENV = "sim"

VALIDATED_SIM_VALIDATIONS = (
    sa.select(
        SkillValidation.skill_id,
        SkillValidation.id,
        SkillValidation.run_at,
        SkillValidation.trials,
        SkillValidation.successes,
        SkillValidation.seeds,
    )
    .join(Skill, Skill.id == SkillValidation.skill_id)
    .where(Skill.status == "validated", SkillValidation.env == SIM_ENV)
    .order_by(SkillValidation.run_at.asc(), SkillValidation.id.asc())
)

NON_DETERMINISTIC_SEEDS = sa.select(SimRun.seed).where(SimRun.deterministic.is_(False)).distinct()


@dataclass(frozen=True)
class ValidationRow:
    """One `skill_validations` row (SPEC 7), as both sources hand it over."""

    skill_id: str
    run_id: int
    run_at: dt.datetime
    trials: int
    successes: int
    seeds: tuple[int, ...]


@dataclass(frozen=True)
class Run:
    """A validation row with the SPEC 11.2-3 determinism verdict resolved."""

    run_id: int
    run_at: dt.datetime
    trials: int
    successes: int
    deterministic: bool

    @property
    def rate(self) -> float:
        return self.successes / self.trials  # SPEC 7 CHECK (trials > 0)


@dataclass(frozen=True)
class SkillTrials:
    """Every recorded sim validation of one validated skill, oldest first."""

    skill_id: str
    runs: tuple[Run, ...]


@dataclass(frozen=True)
class Verdict:
    skill_id: str
    status: Status
    detail: str


def group(
    rows: Iterable[ValidationRow], non_deterministic_seeds: Collection[int]
) -> tuple[SkillTrials, ...]:
    """Bucket validation rows per skill and resolve SPEC 11.2-3 determinism from the seeds."""
    by_skill: dict[str, list[Run]] = defaultdict(list)
    for row in rows:
        usable = not any(seed in non_deterministic_seeds for seed in row.seeds)
        by_skill[row.skill_id].append(
            Run(row.run_id, row.run_at, row.trials, row.successes, usable)
        )
    return tuple(
        SkillTrials(skill_id, tuple(sorted(runs, key=lambda r: (r.run_at, r.run_id))))
        for skill_id, runs in sorted(by_skill.items())
    )


def judge(skill: SkillTrials) -> Verdict:
    """SPEC 14.3 condition 3 for one skill. `undecided` is reported, never silently dropped."""
    usable = [run for run in skill.runs if run.deterministic]
    dropped = len(skill.runs) - len(usable)
    note = f"; {dropped} non-deterministic run(s) excluded (SPEC 11.2-3)" if dropped else ""
    if len(usable) < 2:
        return Verdict(
            skill.skill_id,
            "undecided",
            f"needs a baseline and a replay, got {len(usable)} usable validation(s){note}",
        )
    baseline, replay = usable[0], usable[-1]
    if min(baseline.trials, replay.trials) < MIN_TRIALS:
        return Verdict(
            skill.skill_id,
            "undecided",
            f"too few trials to judge: baseline n={baseline.trials}, replay n={replay.trials}, "
            f"need {MIN_TRIALS}{note}",
        )
    drop = baseline.rate - replay.rate
    detail = (
        f"{baseline.rate:.3f} (n={baseline.trials}) -> {replay.rate:.3f} (n={replay.trials}), "
        f"drop={drop:+.3f}, band={MAX_REGRESSION}{note}"
    )
    return Verdict(skill.skill_id, "regressed" if drop > MAX_REGRESSION else "ok", detail)


class SkillSource(Protocol):
    """Where the validated skill set comes from. Injected: CI has no lab database."""

    def load(self) -> tuple[SkillTrials, ...]: ...


class JsonSkillSource:
    """A committed corpus shaped like the three SPEC 7 tables this harness reads."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> tuple[SkillTrials, ...]:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        validated = {s["id"] for s in data["skills"] if s["status"] == "validated"}
        rows = [
            ValidationRow(
                v["skill_id"],
                int(v["id"]),
                dt.datetime.fromisoformat(v["run_at"]),
                int(v["trials"]),
                int(v["successes"]),
                tuple(int(seed) for seed in v["seeds"]),
            )
            for v in data["skill_validations"]
            if v["skill_id"] in validated and v["env"] == SIM_ENV
        ]
        bad_seeds = {int(r["seed"]) for r in data["sim_runs"] if not r["deterministic"]}
        return group(rows, bad_seeds)


class DbSkillSource:
    """The live SPEC 7 tables on the lab host, over NEML_DB_URL (SPEC 17.3).

    ponytail: `skill_validations` has no determinism column, so SPEC 11.2-3 is resolved
    through the only link SPEC 7 offers -- `skill_validations.seeds` against
    `sim_runs.seed`. Seeds are not unique across candidates, so this over-excludes when
    two campaigns reuse a seed. Add `sim_runs.skill_id` (or a join table) to make it exact.
    """

    def load(self) -> tuple[SkillTrials, ...]:
        return asyncio.run(self._load())

    async def _load(self) -> tuple[SkillTrials, ...]:
        async with get_sessionmaker()() as session:
            records = (await session.execute(VALIDATED_SIM_VALIDATIONS)).all()
            bad_seeds = set((await session.execute(NON_DETERMINISTIC_SEEDS)).scalars().all())
        rows = [
            ValidationRow(r.skill_id, r.id, r.run_at, r.trials, r.successes, tuple(r.seeds))
            for r in records
        ]
        return group(rows, bad_seeds)


def default_source(corpus: Path) -> SkillSource:
    """Corpus by default; `NEML_REGRESSION_SOURCE=db` switches to the lab database.

    `NEML_REGRESSION_CORPUS` points the fixture source at another corpus file, which is
    how the suite is shown to actually fail on a regressed skill.
    """
    if os.environ.get("NEML_REGRESSION_SOURCE") == "db":
        return DbSkillSource()
    return JsonSkillSource(Path(os.environ.get("NEML_REGRESSION_CORPUS") or corpus))
