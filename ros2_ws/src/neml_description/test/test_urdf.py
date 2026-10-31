# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The automatic post-generation checks NEML_SPEC.md SS12.2 makes mandatory,
run against the expanded quadruped_v2 URDF: mass > 0, inertia triangle
inequality, collision is not the visual mesh, total mass within +-10% of the
measured genome mass, and the SS13.3 joint limits."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

xacro = pytest.importorskip("xacro", reason="xacro comes from a sourced ROS 2 Jazzy install")

PKG = Path(__file__).resolve().parent.parent
XACRO = PKG / "urdf" / "quadruped_v2.urdf.xacro"

# SS13.3 genome values this description must keep matching.
TOTAL_DOF = 16
EFFORT_NM = 2.5
VELOCITY_RADS = 6.0
MEASURED_MASS_KG = 2.40
JOINT_SUFFIXES = ("hip_yaw", "hip_pitch", "knee", "ankle")
LEG_PREFIXES = ("fl", "fr", "rl", "rr")


@pytest.fixture(scope="module")
def robot():
    doc = xacro.process_file(str(XACRO), mappings={"use_sim": "true"})
    return ET.fromstring(doc.toxml())


def _revolute(robot):
    return [j for j in robot.findall("joint") if j.get("type") == "revolute"]


def test_sixteen_actuated_joints(robot):
    joints = _revolute(robot)
    assert len(joints) == TOTAL_DOF
    names = {j.get("name") for j in joints}
    assert names == {f"{p}_{s}" for p in LEG_PREFIXES for s in JOINT_SUFFIXES}


def test_joint_limits_match_genome(robot):
    for joint in _revolute(robot):
        limit = joint.find("limit")
        assert limit is not None, joint.get("name")
        assert float(limit.get("effort")) == pytest.approx(EFFORT_NM)
        assert float(limit.get("velocity")) == pytest.approx(VELOCITY_RADS)
        assert float(limit.get("lower")) < float(limit.get("upper"))


def test_collision_is_never_the_visual_mesh(robot):
    """SS12.2: collision mesh != visual mesh. Primitives or convex hulls only."""
    saw_visual_mesh = False
    for link in robot.findall("link"):
        for visual in link.findall("visual"):
            if visual.find("geometry/mesh") is not None:
                saw_visual_mesh = True
        for collision in link.findall("collision"):
            assert collision.find("geometry/mesh") is None, (
                f"{link.get('name')}: collision uses a mesh"
            )
            assert list(collision.find("geometry")), (
                f"{link.get('name')}: collision has no geometry"
            )
    assert saw_visual_mesh, "no visual mesh at all - the check would be vacuous"


def test_inertia_is_physical(robot):
    """mass > 0 and the triangle inequality on the principal moments."""
    for link in robot.findall("link"):
        inertial = link.find("inertial")
        if inertial is None:
            continue
        mass = float(inertial.find("mass").get("value"))
        assert mass > 0.0, link.get("name")
        i = inertial.find("inertia")
        ixx, iyy, izz = (float(i.get(k)) for k in ("ixx", "iyy", "izz"))
        assert min(ixx, iyy, izz) > 0.0, link.get("name")
        assert ixx + iyy >= izz, link.get("name")
        assert iyy + izz >= ixx, link.get("name")
        assert izz + ixx >= iyy, link.get("name")


def test_total_mass_within_ten_percent_of_measured(robot):
    total = sum(
        float(link.find("inertial/mass").get("value"))
        for link in robot.findall("link")
        if link.find("inertial") is not None
    )
    assert total == pytest.approx(MEASURED_MASS_KG, rel=0.10), f"total {total} kg"


def test_declared_sensors_match_genome(robot):
    names = {s.get("name") for s in robot.findall("gazebo/sensor")}
    assert {"bno085", "d405"} <= names
    # 2 x ina226 rails (SS13.3 count: 2)
    links = {link.get("name") for link in robot.findall("link")}
    assert {"ina226_5v_link", "ina226_3v3_link"} <= links


def test_ros2_control_exposes_all_sixteen(robot):
    control = robot.find("ros2_control")
    assert control is not None
    assert len(control.findall("joint")) == TOTAL_DOF
