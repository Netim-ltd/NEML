# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""URDF/xacro assembly: xacro, the joint tree, primitives, colours, poses - and what is refused."""

from __future__ import annotations

import math

import numpy as np
import pytest

from neml_brain.evolution.urdf_assembly import (
    UrdfError,
    assemble,
    evaluate,
    includes_of,
    link_matrices,
)

XACRO = """<?xml version="1.0"?>
<robot xmlns:xacro="http://www.ros.org/wiki/xacro" name="demo">
  <xacro:property name="len" value="0.2"/>
  <xacro:macro name="leg" params="name left side:=1">
    <link name="${name}">
      <visual>
        <xacro:if value="${left}"><geometry><mesh filename="package://p/l.stl" scale="0.001 0.001 0.001"/></geometry></xacro:if>
        <xacro:unless value="${left}"><geometry><mesh filename="package://p/r.stl" scale="0.001 0.001 0.001"/></geometry></xacro:unless>
        <origin xyz="0 0 -${len/2}" rpy="0 0 ${pi}"/>
      </visual>
    </link>
    <joint name="j_${name}" type="revolute">
      <parent link="base"/><child link="${name}"/><origin xyz="${side*0.1} 0.05 0"/>
      <axis xyz="0 1 0"/><limit lower="-1" upper="1" effort="1" velocity="1"/>
    </joint>
  </xacro:macro>
  <link name="base"><visual><geometry><mesh filename="a/b/Body.STL"/></geometry></visual></link>
  <xacro:leg name="fl" left="true"/>
  <xacro:leg name="fr" left="false" side="-1"/>
</robot>"""


def by_link(found):
    return {p["link"]: p for p in found}


def test_the_restricted_xacro_places_every_mesh_in_the_zero_pose_in_millimetres():
    summary, found, rig, _ = assemble(XACRO)
    assert summary["links"] == 3 and summary["joints"] == 2 and summary["movable_joints"] == 2
    p = by_link(found)
    assert p["base"]["mesh"] == "body.stl" and p["base"]["factor"] == 1000.0  # no scale: metres
    assert p["fl"]["mesh"] == "l.stl" and p["fr"]["mesh"] == "r.stl"  # if / unless
    assert p["fl"]["pos"] == [100.0, 50.0, -100.0] and p["fr"]["pos"] == [-100.0, 50.0, -100.0]
    assert p["fl"]["factor"] == 1.0  # scale 0.001: the mesh is already in millimetres
    x, y, z, w = p["fl"]["quat"]  # yaw of pi about z
    assert (abs(x), abs(y), round(abs(z), 3)) == (0, 0, 1.0) and abs(w) < 1e-3
    assert rig["root"] == "base" and [j["name"] for j in rig["joints"]] == ["j_fl", "j_fr"]
    assert p["fl"]["vpos"] == [0.0, 0.0, -100.0]  # the visual's pose in its own link frame


def test_expressions_are_arithmetic_only():
    assert evaluate("1 + 2 * 3", {}) == 7 and evaluate("-a / 2", {"a": 4.0}) == -2.0
    assert round(evaluate("sin(pi / 2)", {}), 6) == 1.0 and evaluate("a == 'x'", {"a": "x"}) is True
    for evil in (
        "__import__('os').system('x')",
        "().__class__",
        "open('f')",
        "nothere + 1",
        "'abc'.upper()",
        "x.__class__",
    ):
        with pytest.raises(UrdfError):
            evaluate(evil, {"x": 1})


def test_expressions_support_conditionals_lists_dicts_and_membership():
    assert evaluate("1 if a > 2 else 0", {"a": 3}) == 1 and evaluate("[1, 2, 3][1]", {}) == 2
    assert evaluate("{'a': 5}['a']", {}) == 5 and evaluate("'x' in ['x', 'y']", {}) is True
    assert (
        evaluate("'%d-%s' % [3, 'z']", {}) == "3-z" and evaluate("len('abc') + floor(2.7)", {}) == 5
    )
    assert evaluate("str(1.5) + 'm'", {}) == "1.5m"


def test_what_the_restricted_xacro_cannot_do_is_reported_not_guessed():
    for body in (
        '<xacro:include filename="x.xacro"/>',  # no resolver
        '<xacro:macro name="m" params="*block"/><xacro:m/>',  # the block is missing
        "<xacro:nonsense/>",
        '<xacro:property name="p"/>',  # neither a value nor a block
        '<xacro:property name="y" value="${load_yaml(\'a.yaml\')}"/>',  # no resolver for the yaml
        '<link name="a"><visual><geometry><mesh filename="$(unknown_command x)/a.stl"/></geometry></visual></link>',
    ):
        with pytest.raises(UrdfError):
            assemble(f'<robot xmlns:xacro="http://www.ros.org/wiki/xacro" name="x">{body}</robot>')
    for bad in ('<!DOCTYPE r [<!ENTITY a "x">]><robot name="&a;"/>', "<notrobot/>", "<robot"):
        with pytest.raises(UrdfError):
            assemble(bad)


def test_includes_args_find_and_blocks_work_with_a_resolver():
    libs = {
        "robots/macros.xacro": """<robot xmlns:xacro="http://www.ros.org/wiki/xacro">
          <xacro:macro name="wheel" params="name *origin">
            <link name="${name}"><visual><geometry><cylinder radius="0.05" length="0.02"/></geometry>
              <material name="blue"><color rgba="0 0 1 1"/></material></visual></link>
            <joint name="j_${name}" type="continuous"><parent link="base"/><child link="${name}"/>
              <xacro:insert_block name="origin"/><axis xyz="0 1 0"/></joint>
          </xacro:macro></robot>"""
    }

    def resolver(filename, base):
        assert base == "robots/main.xacro"
        for path, text in libs.items():
            if filename.endswith("macros.xacro"):
                return path, text
        return None

    text = """<robot xmlns:xacro="http://www.ros.org/wiki/xacro" name="car">
      <xacro:arg name="gap" default="0.3"/>
      <xacro:include filename="$(find car_description)/robots/macros.xacro"/>
      <link name="base"><visual><geometry><box size="0.4 0.2 0.1"/></geometry></visual></link>
      <xacro:wheel name="left"><origin xyz="0 $(arg gap) 0"/></xacro:wheel>
      <xacro:wheel name="right"><origin xyz="0 -$(arg gap) 0"/></xacro:wheel>
    </robot>"""
    summary, found, rig, included = assemble(text, resolver, "robots/main.xacro")
    assert included == ["robots/macros.xacro"] and summary["shapes"] == {"box": 1, "cylinder": 2}
    p = by_link(found)
    assert p["base"]["shape"] == {"type": "box", "size": [400.0, 200.0, 100.0]}
    assert p["left"]["shape"] == {"type": "cylinder", "radius": 50.0, "length": 20.0}
    assert p["left"]["pos"] == [0.0, 300.0, 0.0] and p["right"]["pos"] == [0.0, -300.0, 0.0]
    assert p["left"]["color"] == "#0000ff" and "color" not in p["base"]
    assert [j["type"] for j in rig["joints"]] == ["continuous", "continuous"]
    assert (rig["joints"][0]["lower"], round(rig["joints"][0]["upper"], 3)) == (
        -round(math.pi, 6),
        round(math.pi, 3),
    )
    assert includes_of(text) == ["$(find car_description)/robots/macros.xacro"]


def test_yaml_properties_eval_env_and_the_property_scopes():
    yaml_text = "arm:\n  length: 0.4\n  joints: [a, b]\nname: demo\n"

    def resolver(filename, base):
        assert base == "robots/main.xacro"
        return ("cfg/arm.yaml", yaml_text) if filename.endswith("arm.yaml") else None

    text = """<robot xmlns:xacro="http://www.ros.org/wiki/xacro" name="$(eval 'r' + 'x')">
      <xacro:property name="cfg" value="${load_yaml('$(find pkg)/cfg/arm.yaml')}"/>
      <xacro:macro name="m" params="n">
        <xacro:property name="made" value="${n * 2}" scope="global"/>
      </xacro:macro>
      <xacro:m n="3"/>
      <link name="${cfg.name}_${cfg['arm']['joints'][1]}"><visual><geometry>
        <box size="${cfg.arm.length} ${made / 6} $(env HOME)0.1"/></geometry></visual></link>
    </robot>"""
    summary, found, _, _ = assemble(text, resolver, "robots/main.xacro")
    assert summary["robot"] == "rx" and found[0]["link"] == "demo_b"
    assert found[0]["shape"]["size"] == [400.0, 1000.0, 100.0]  # made = 6 (global), env is empty


def test_element_attribute_double_star_blocks_and_block_properties():
    text = """<robot xmlns:xacro="http://www.ros.org/wiki/xacro" name="r">
      <xacro:property name="shape"><box size="0.1 0.2 0.3"/></xacro:property>
      <xacro:macro name="wrap" params="n **body">
        <link name="${n}"><visual><geometry><xacro:insert_block name="body"/></geometry></visual></link>
      </xacro:macro>
      <xacro:wrap n="a"><holder><sphere radius="0.05"/></holder></xacro:wrap>
      <link name="b"><visual><geometry><xacro:insert_block name="shape"/></geometry></visual></link>
      <xacro:element xacro:name="link" name="c"><xacro:attribute name="extra" value="1"/>
        <visual><geometry><cylinder radius="0.01" length="0.02"/></geometry></visual></xacro:element>
    </robot>"""
    _, found, _, _ = assemble(text)
    shapes = {p["link"]: p["shape"] for p in found}
    assert shapes["a"] == {"type": "sphere", "radius": 50.0}  # '**' inserts the block's children
    assert shapes["b"]["size"] == [100.0, 200.0, 300.0] and shapes["c"]["type"] == "cylinder"


def test_a_missing_include_and_a_missing_arg_are_errors():
    with pytest.raises(UrdfError, match="not found"):
        assemble(
            '<robot xmlns:xacro="http://www.ros.org/wiki/xacro"><xacro:include filename="nope.xacro"/></robot>',
            lambda f, b: None,
        )
    with pytest.raises(UrdfError, match="no default"):
        assemble('<robot name="$(arg x)"/>')


def test_a_plain_urdf_chain_composes_rotations_and_offsets():
    urdf = """<robot name="r"><link name="a"/><link name="b"><visual><geometry><mesh filename="m.stl" scale="1 1 1"/></geometry>
      <origin xyz="1 0 0"/></visual></link><joint name="j" type="fixed"><parent link="a"/><child link="b"/>
      <origin xyz="0 1 0" rpy="0 0 1.5707963"/></joint></robot>"""
    _, found, _, _ = assemble(urdf)
    px, py, pz = found[0]["pos"]
    assert (round(px), round(py), round(pz)) == (
        0,
        2000,
        0,
    )  # the visual's x offset rotated by 90 degrees
    assert math.isclose(found[0]["quat"][2], math.sqrt(0.5), abs_tol=1e-3)


def test_non_uniform_mesh_scale_is_kept_per_axis():
    _, found, _, _ = assemble(
        '<robot name="r"><link name="a"><visual><geometry><mesh filename="m.stl" scale="0.001 0.002 0.001"/></geometry></visual></link></robot>'
    )
    assert found[0]["factor"] == 1.0 and found[0]["scale3"] == [1.0, 2.0, 1.0]


POSE = """<robot name="arm"><link name="base"/><link name="upper"><visual><geometry><box size="0.1 0.1 0.1"/></geometry>
  <origin xyz="0 0 0.05"/></visual></link><link name="lower"><visual><geometry><sphere radius="0.02"/></geometry></visual></link>
  <link name="slider"/><link name="follower"/>
  <joint name="shoulder" type="revolute"><parent link="base"/><child link="upper"/><origin xyz="0 0 0.1"/><axis xyz="0 1 0"/><limit lower="-3" upper="3"/></joint>
  <joint name="elbow" type="revolute"><parent link="upper"/><child link="lower"/><origin xyz="0 0 0.1"/><axis xyz="0 1 0"/><limit lower="-3" upper="3"/>
    <mimic joint="shoulder" multiplier="2" offset="0.1"/></joint>
  <joint name="rail" type="prismatic"><parent link="base"/><child link="slider"/><axis xyz="1 0 0"/><limit lower="0" upper="0.5"/></joint>
  <joint name="fixed1" type="fixed"><parent link="slider"/><child link="follower"/><origin xyz="0 0.1 0"/></joint></robot>"""


def test_posing_turns_revolute_joints_slides_prismatic_ones_and_follows_mimic():
    _, _, rig, _ = assemble(POSE)
    zero = link_matrices(rig)
    assert np.allclose(zero["upper"][:3, 3], [0, 0, 100]) and np.allclose(
        zero["lower"][:3, 3], [0, 0, 200]
    )
    posed = link_matrices(rig, {"shoulder": math.pi / 2, "rail": 0.25})
    # the shoulder turns +90 degrees about y: the upper arm's local +z points along world +x
    assert np.allclose(posed["lower"][:3, 3], [100, 0, 100], atol=1e-6)
    assert np.allclose(posed["slider"][:3, 3], [250, 0, 0]) and np.allclose(
        posed["follower"][:3, 3], [250, 100, 0]
    )
    # elbow = 2 * shoulder + 0.1 (mimic): the lower link's rotation is the shoulder's plus the elbow's
    angle = math.pi / 2 + (2 * math.pi / 2 + 0.1)
    expected = np.array(
        [[math.cos(angle), 0, math.sin(angle)], [0, 1, 0], [-math.sin(angle), 0, math.cos(angle)]]
    )
    assert np.allclose(posed["lower"][:3, :3], expected, atol=1e-5)
