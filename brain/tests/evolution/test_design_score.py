# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
from copy import deepcopy

from neml_brain.evolution.design_score import mission_score

from .test_generative import PLAN


def _bigger_wheels(plan, factor):
    out = deepcopy(plan)
    for lk in out["links"]:
        if "wheel" in str(lk["name"]).lower():
            lk["dims_mm"] = [d * factor for d in lk["dims_mm"]]
    return out


def test_plans_that_differ_score_differently_and_a_wheel_that_cannot_climb_the_step_loses():
    small, big = _bigger_wheels(PLAN, 0.5), PLAN
    s1, i1 = mission_score(small)
    s2, i2 = mission_score(big)
    assert s1 != s2
    if i1["drivable"] and i2["drivable"]:
        assert i1["step"] <= i2["step"]


def test_a_plan_the_simulation_cannot_drive_scores_below_a_drivable_one():
    broken = deepcopy(PLAN)
    for lk in broken["links"]:
        lk["joint"]["z"] = float(lk["joint"]["z"]) + 900
    assert mission_score(broken)[0] < mission_score(PLAN)[0]
