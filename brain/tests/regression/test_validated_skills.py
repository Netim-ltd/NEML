# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 18.1 / CI gate 7: `pytest -m regression` replays every validated skill (T-038).

One test per skill, parametrised off the skill table itself, so a skill joins the gate
the day its status becomes 'validated' -- nothing here is a hardcoded list.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from neml_brain.testing.skills import SkillTrials, default_source, judge

pytestmark = pytest.mark.regression

CORPUS = Path(__file__).parent / "corpus" / "skills.json"

# Collection-time, because the parametrisation is the skill set.
SKILLS = default_source(CORPUS).load()


def test_the_validated_skill_set_is_not_empty() -> None:
    """An empty skill set makes gate 7 vacuous -- exactly the T-038 failure mode.

    ponytail: this fails loudly on a lab database with nothing validated yet. Loud beats
    a gate that passes by selecting nothing; relax it only if an empty library is ever
    a legitimate steady state.
    """
    assert SKILLS, "no validated skill to replay: gate 7 would pass by selecting nothing"


@pytest.mark.parametrize("skill", SKILLS, ids=lambda s: s.skill_id)
def test_skill_has_not_regressed(skill: SkillTrials) -> None:
    """SPEC 14.3 condition 3: still >= the old success rate - 5%."""
    verdict = judge(skill)
    if verdict.status == "undecided":
        # Reported, never silently skipped: pytest prints this in the warnings summary.
        warnings.warn(
            f"{skill.skill_id}: not judgeable -- {verdict.detail}", UserWarning, stacklevel=2
        )
    assert verdict.status != "regressed", f"{skill.skill_id}: {verdict.detail}"
