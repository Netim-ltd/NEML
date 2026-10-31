# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The guard on CI gate 7 itself, plus the harness's own checks.

Deliberately NOT marked `regression`: it has to run in the ordinary unit suite, because
its job is to catch the state where `pytest -m regression` selects nothing and passes.
That is how gate 7 was vacuous before T-038 and it must not come back.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from sqlalchemy.dialects import postgresql

from neml_brain.testing.skills import (
    NON_DETERMINISTIC_SEEDS,
    VALIDATED_SIM_VALIDATIONS,
    JsonSkillSource,
    Verdict,
    judge,
)

GUARD = Path(__file__)
REGRESSION_DIR = GUARD.parent
BRAIN_DIR = REGRESSION_DIR.parents[1]
MARKER = "pytestmark = pytest.mark.regression"


def _verdicts(corpus: str) -> dict[str, Verdict]:
    skills = JsonSkillSource(REGRESSION_DIR / "corpus" / corpus).load()
    return {v.skill_id: v for v in map(judge, skills)}


# --------------------------------------------------------------- the gate 7 guard


def test_the_regression_suite_collects_at_least_one_test() -> None:
    """pytest exit 5 means nothing was collected -- a green gate that tested nothing."""
    proc = subprocess.run(  # noqa: S603 - fixed argv, sys.executable, no shell
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "--strict-markers",
            "-p",
            "no:cacheprovider",
            "-m",
            "regression",
            "tests/regression",
        ],
        cwd=BRAIN_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (
        f"`pytest -m regression` collected nothing (exit {proc.returncode}):\n"
        f"{proc.stdout}\n{proc.stderr}"
    )


def test_every_regression_module_declares_the_marker() -> None:
    """Anything dropped in this directory joins gate 7, or the gate erodes again."""
    modules = sorted(p for p in REGRESSION_DIR.rglob("test_*.py") if p != GUARD)
    assert modules, "brain/tests/regression holds no regression test module"
    for path in modules:
        assert MARKER in path.read_text(encoding="utf-8"), (
            f"{path.name} must declare `{MARKER}` (SPEC 18.1, CI gate 7)"
        )


# ------------------------------------------------------- the harness's own checks


def test_a_regressed_skill_fails_the_suite() -> None:
    """The proof the gate can detect anything: 0.917 -> 0.625 is outside the 5% band."""
    verdict = _verdicts("skills_regressed.json")["pick_payload@2"]
    assert verdict.status == "regressed", verdict.detail


def test_the_shipped_corpus_has_no_regression() -> None:
    assert not [v for v in _verdicts("skills.json").values() if v.status == "regressed"]


def test_non_deterministic_runs_are_excluded_not_counted() -> None:
    """SPEC 11.2-3: turn_in_place's latest replay carries a drifted seed.

    Counted, it reads 0.875 -> 0.500 and would fail the band. Excluded, the judgement
    falls back to the last two usable validations and the skill is fine.
    """
    verdict = _verdicts("skills.json")["turn_in_place@2"]
    assert verdict.status == "ok", verdict.detail
    assert "1 non-deterministic run(s) excluded" in verdict.detail


def test_too_few_trials_is_reported_not_skipped() -> None:
    verdict = _verdicts("skills.json")["climb_small_obstacle@3"]
    assert verdict.status == "undecided"
    assert "too few trials to judge" in verdict.detail


def test_only_validated_skills_are_replayed() -> None:
    """stand_still@5 is a candidate and collapses to 0.25; it is not this gate's business."""
    assert "stand_still@5" not in _verdicts("skills.json")


def test_real_env_validations_are_not_replayed() -> None:
    """walk_flat's newest row is a `real` run at 0.417; SPEC 18.1 gate 7 is the sim gate."""
    verdict = _verdicts("skills.json")["walk_flat@4"]
    assert verdict.status == "ok", verdict.detail
    assert "0.875" in verdict.detail


def test_db_source_reads_validated_sim_rows_only() -> None:
    """The lab-host query, compiled -- no database needed to check what it asks for."""
    sql = str(
        VALIDATED_SIM_VALIDATIONS.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "JOIN skills ON skills.id = skill_validations.skill_id" in sql
    assert "skills.status = 'validated'" in sql
    assert "skill_validations.env = 'sim'" in sql
    assert "ORDER BY skill_validations.run_at ASC, skill_validations.id ASC" in sql

    seeds_sql = str(
        NON_DETERMINISTIC_SEEDS.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "SELECT DISTINCT sim_runs.seed" in seeds_sql
    assert "sim_runs.deterministic IS false" in seeds_sql
