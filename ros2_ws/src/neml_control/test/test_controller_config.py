# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Locks the two numbers the whole sim-to-real protocol rests on: the 1 kHz
controller manager rate (NEML_SPEC.md SS2 / SS11.1) and the SS13.3 genome
limits. Also checks that no controller silently drops a joint."""

from pathlib import Path

import pytest
import yaml

PKG = Path(__file__).resolve().parent.parent
CONTROLLERS = PKG / "config" / "controllers.yaml"
LIMITS = PKG / "config" / "joint_limits.yaml"

UPDATE_RATE_HZ = 1000
EFFORT_NM = 2.5
VELOCITY_RADS = 6.0
JOINTS = [
    f"{prefix}_{suffix}"
    for prefix in ("fl", "fr", "rl", "rr")
    for suffix in ("hip_yaw", "hip_pitch", "knee", "ankle")
]


@pytest.fixture(scope="module")
def controllers():
    return yaml.safe_load(CONTROLLERS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def limits():
    return yaml.safe_load(LIMITS.read_text(encoding="utf-8"))["joint_limits"]


def test_update_rate_is_one_khz(controllers):
    assert controllers["controller_manager"]["ros__parameters"]["update_rate"] == UPDATE_RATE_HZ


def test_both_command_controllers_are_declared(controllers):
    cm = controllers["controller_manager"]["ros__parameters"]
    assert cm["joint_trajectory_controller"]["type"].startswith("joint_trajectory_controller/")
    assert cm["joint_effort_controller"]["type"].startswith("effort_controllers/")
    assert cm["joint_state_broadcaster"]["type"].startswith("joint_state_broadcaster/")


@pytest.mark.parametrize("controller", ["joint_trajectory_controller", "joint_effort_controller"])
def test_controller_covers_all_sixteen_joints(controllers, controller):
    assert controllers[controller]["ros__parameters"]["joints"] == JOINTS


def test_limits_cover_every_joint(limits):
    assert sorted(limits) == sorted(JOINTS)


@pytest.mark.parametrize("joint", JOINTS)
def test_limits_match_genome(limits, joint):
    entry = limits[joint]
    assert entry["has_effort_limits"] is True
    assert entry["has_velocity_limits"] is True
    assert entry["max_effort"] == pytest.approx(EFFORT_NM)
    assert entry["max_velocity"] == pytest.approx(VELOCITY_RADS)
    assert entry["min_position"] < entry["max_position"]
