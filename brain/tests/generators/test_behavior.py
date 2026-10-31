# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Behaviour tree emission: deterministic, schema constrained, no model."""

import xml.etree.ElementTree as ET  # noqa: S405 - our own generated trees

import pytest

from neml_brain.generators import behavior

PARAMS = {
    "M1_straight": {"min_soc": 0.3, "distance_m": 2.0, "speed_mps": 0.2, "gait": "walk"},
    "M2_turn": {"min_soc": 0.3, "angle_deg": 180, "yaw_rate_rads": 0.6},
    "M3_step": {
        "min_soc": 0.35,
        "step_height_mm": 40,
        "lift_mm": 70,
        "speed_mps": 0.15,
        "torque_limit_nm": 2.0,
        "attempts": 3,
    },
    "M4_stand": {"min_soc": 0.2, "duration_s": 30, "stiffness": 0.6},
    "M5_payload": {
        "min_soc": 0.4,
        "payload_g": 500,
        "distance_m": 2.0,
        "speed_mps": 0.2,
        "gait": "walk",
    },
    "climb_small_obstacle": {
        "min_soc": 0.35,
        "max_height_mm": 60,
        "lift_mm": 90,
        "torque_limit_nm": 2.0,
        "approach_mps": 0.2,
        "retreat_m": 0.4,
    },
}


def test_every_skill_has_parameters_under_test():
    assert set(PARAMS) == set(behavior.SKILLS)


@pytest.mark.parametrize("skill_key", sorted(PARAMS))
def test_trees_are_valid_btcpp_v4(skill_key):
    xml = behavior.render(skill_key, PARAMS[skill_key])
    root = ET.fromstring(xml)  # noqa: S314 - our own output
    assert root.tag == "root"
    assert root.get("BTCPP_format") == "4"
    assert root.get("main_tree_to_execute") == skill_key
    tree = root.find("BehaviorTree")
    assert tree is not None and tree.get("ID") == skill_key
    assert len(list(tree)) == 1  # exactly one root node
    assert tree.find(".//CheckBattery") is not None  # every skill guards the battery


@pytest.mark.parametrize("skill_key", sorted(PARAMS))
def test_emission_is_deterministic(skill_key):
    params = PARAMS[skill_key]
    reordered = dict(reversed(list(params.items())))
    assert behavior.render(skill_key, params) == behavior.render(skill_key, reordered)
    assert behavior.input_hash(skill_key, params) == behavior.input_hash(skill_key, reordered)


def test_generate_writes_the_bt_path(tmp_path):
    artifact = behavior.generate("M1_straight", PARAMS["M1_straight"], tmp_path / "bt")
    assert artifact.bt_path.exists()
    assert artifact.bt_path.name == f"M1_straight-{artifact.input_sha256[:12]}.xml"
    assert artifact.bt_path.read_text(encoding="utf-8") == artifact.xml
    again = behavior.generate("M1_straight", PARAMS["M1_straight"], tmp_path / "bt")
    assert again == artifact


def test_parameters_change_the_tree_and_the_path(tmp_path):
    first = behavior.generate("M1_straight", PARAMS["M1_straight"], tmp_path)
    second = behavior.generate(
        "M1_straight", {**PARAMS["M1_straight"], "distance_m": 3.0}, tmp_path
    )
    assert first.bt_path != second.bt_path
    assert first.xml != second.xml


def test_unknown_skill_and_bad_parameters_are_refused():
    with pytest.raises(behavior.UnknownSkill):
        behavior.render("teleport", {})
    with pytest.raises(behavior.ParamError):
        behavior.render("M1_straight", {**PARAMS["M1_straight"], "speed_mps": 9.0})
    with pytest.raises(behavior.ParamError):
        behavior.render("M1_straight", {**PARAMS["M1_straight"], "extra": 1})
    with pytest.raises(behavior.ParamError):
        behavior.render("M1_straight", {"min_soc": 0.3})
