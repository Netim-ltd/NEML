# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Screw holes appear under the bought parts that rest on a designed part."""

from neml_brain.evolution.judges import equip
from neml_brain.evolution.mounts import mount_features

from .test_generative import PLAN


def test_boards_and_batteries_on_the_chassis_get_four_corner_holes_each_and_nothing_hangs_outside_it():
    plan = equip(PLAN)
    base = plan["links"][0]
    holes = mount_features(plan, base, [-80, -50, -20, 80, 50, 20])
    assert holes and all(h["f"] == "hole" and h["axis"] == "z" and h["d"] == 3.2 for h in holes)
    assert all(-80 <= h["at"][0] <= 80 and -50 <= h["at"][1] <= 50 for h in holes)
    assert all(h["dir"] == "-" and h["at"][2] == 20 for h in holes)  # drilled down from the top face
    assert len({tuple(h["at"]) for h in holes}) == len(holes)


def test_a_part_with_no_bought_children_or_a_side_mounted_one_gets_no_holes():
    plan = equip(PLAN)
    wheel = next(lk for lk in plan["links"] if lk["name"] == "wheel_l")
    assert mount_features(plan, wheel, [-30, -10, -30, 30, 10, 30]) == []
    assert mount_features(plan, plan["links"][0], [-80, -50, -20, 80, 50, 60]) == []  # the children now sit inside, not on a face
