# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A generated robot is simulated as itself: its own body, wheels and masses."""

import xml.etree.ElementTree as ET
from copy import deepcopy

import pytest

from neml_brain.evolution.judges import equip, robot_issues
from neml_brain.evolution.robot_sdf import NotDrivable, sdf_of

from .test_generative import PLAN


def _tree(sdf: str) -> ET.Element:
    return ET.fromstring(sdf.split("?>", 1)[1])  # noqa: S314


def test_the_planned_robot_becomes_a_model_with_its_own_wheels_and_a_drive_plugin():
    sdf, info = sdf_of(equip(PLAN), camera=True)
    wheel = next(lk for lk in equip(PLAN)["links"] if lk["name"] == "wheel_l")
    root = _tree(sdf)
    assert {link.get("name") for link in root.iter("link")} >= {"base_link", "wheel_l", "wheel_r"}
    assert info["wheels"] == 2 and info["casters"] == 2 and info["wheel_radius_mm"] == round(max(wheel["dims_mm"][0], wheel["dims_mm"][2]) / 2) and info["track_mm"] == 120
    assert [e.text for e in root.iter("left_joint")] == ["wheel_l_joint"]
    assert [e.text for e in root.iter("right_joint")] == ["wheel_r_joint"]
    assert root.find(".//sensor[@name='cam']") is not None
    assert info["mass_kg"] == pytest.approx(sum(float(lk["mass_g"]) for lk in equip(PLAN)["links"]) / 1000, rel=0.01)


def test_a_bigger_robot_is_a_different_model_not_the_same_chassis_with_another_mass():
    big = equip(deepcopy(PLAN))
    big["links"][0]["dims_mm"] = [400, 240, 60]
    a, b = _tree(sdf_of(equip(PLAN))[0]), _tree(sdf_of(big)[0])
    box = lambda t: t.find(".//collision[@name='c_base']//size").text  # noqa: E731
    assert box(a) != box(b)


@pytest.mark.parametrize(
    "mutate, why",
    [
        (lambda p: [lk.update(source="bought") for lk in p["links"] if lk["name"] == "wheel_r"] and p["links"].pop(2), "1 tekerlek"),
        (lambda p: p["links"][1]["joint"].update(y=-60), "tek yanında"),
        (lambda p: [lk["joint"].update(axis="z") for lk in p["links"] if lk["name"].startswith("wheel")], "eksenleri"),
        (lambda p: [lk["joint"].update(z=-100) for lk in p["links"] if lk["name"].startswith("lipo")], "aşağıda"),
    ],
)
def test_a_robot_that_cannot_be_driven_says_why(mutate, why):
    plan = equip(deepcopy(PLAN))
    mutate(plan)
    with pytest.raises(NotDrivable, match=why):
        sdf_of(plan)


def test_the_plan_judge_sends_back_a_wheeled_plan_the_simulation_cannot_drive():
    plan = equip(deepcopy(PLAN))
    assert not [i for i in robot_issues(plan) if i.startswith("sürülemez")]
    plan["links"][1]["joint"]["y"] = -60
    assert any(i.startswith("sürülemez") for i in robot_issues(plan))
