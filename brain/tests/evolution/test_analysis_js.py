# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Collisions, centre of mass and standing, as the viewer computes them (analysis.js, run with node)."""

from __future__ import annotations

import json
import math
import shutil
import subprocess

import pytest

from neml_brain.evolution.urdf_assembly import assemble
from neml_brain.paths import REPO_ROOT

ANALYSIS_JS = REPO_ROOT / "dotnet" / "Neml.Web" / "wwwroot" / "js" / "analysis.js"
Q0 = [0, 0, 0, 1]
Q45 = [0, 0, math.sin(math.pi / 8), math.cos(math.pi / 8)]  # 45 degrees about z

RIG = {
    "root": "base",
    "joints": [
        {"name": "weld", "type": "fixed", "parent": "base", "child": "plate"},
        {"name": "shoulder", "type": "revolute", "parent": "plate", "child": "arm"},
        {"name": "wrist", "type": "revolute", "parent": "arm", "child": "tip"},
    ],
}

SCRIPT = """
import * as a from %r;
let text = '';
for await (const chunk of process.stdin) text += chunk;
const f = JSON.parse(text);
const box = (c, h, q = [0, 0, 0, 1]) => ({ c, h, q });
const out = {};
out.apart = a.overlap(box([0, 0, 0], [10, 10, 10]), box([25, 0, 0], [10, 10, 10]));
out.touching = a.overlap(box([0, 0, 0], [10, 10, 10]), box([20, 0, 0], [10, 10, 10]));
out.inside = a.overlap(box([0, 0, 0], [10, 10, 10]), box([5, 5, 5], [10, 10, 10]));
out.turned_apart = a.overlap(box([0, 0, 0], [10, 10, 10]), box([25, 0, 0], [10, 10, 10], f.q45));
out.turned_in = a.overlap(box([0, 0, 0], [10, 10, 10]), box([20, 0, 0], [10, 10, 10], f.q45));
const items = [
  { id: 'a', link: 'l1', box: box([0, 0, 0], [10, 10, 10]) },
  { id: 'b', link: 'l1', box: box([5, 0, 0], [10, 10, 10]) },
  { id: 'c', link: 'l2', box: box([8, 0, 0], [10, 10, 10]) },
  { id: 'd', link: 'l3', box: box([9, 0, 0], [10, 10, 10]) },
  { id: 'e', link: 'l4', box: box([200, 0, 0], [10, 10, 10]) },
];
out.collisions = a.collisions(items, [['l1', 'l2']]);
out.com = a.centreOfMass([{ m: 1, p: [0, 0, 0] }, { m: 3, p: [4, 0, 8] }]);
out.no_mass = a.centreOfMass([{ m: 0, p: [1, 1, 1] }]);
out.hull = a.hull2d([[0, 0], [4, 0], [4, 4], [0, 4], [2, 2], [2, 0], [1, 3]]);
const square = [[0, 0], [10, 0], [10, 10], [0, 10]];
out.margin_in = a.insideMargin([5, 5], square);
out.margin_edge = a.insideMargin([10, 5], square);
out.margin_out = a.insideMargin([14, 5], square);
const feet = [[0, 0], [100, 0], [100, 60], [0, 60]].map(([x, y]) => box([x, y, 5], [5, 5, 5]));
const body = box([50, 30, 80], [60, 40, 10]);
out.stand = a.stability([...feet, body], [50, 30, 80]);
out.tip = a.stability([...feet, body], [140, 30, 80]);
out.one_foot = a.stability([feet[0], body], [50, 30, 80]);
out.nothing = a.stability([], [0, 0, 0]);
out.depth_in = a.depth(box([0, 0, 0], [10, 10, 10]), box([15, 0, 0], [10, 10, 10]));
out.depth_apart = a.depth(box([0, 0, 0], [10, 10, 10]), box([40, 0, 0], [10, 10, 10])) <= 0;
const shallow = [
  { id: 'a', link: 'g1', box: box([0, 0, 0], [10, 10, 10]) },
  { id: 'b', link: 'g2', box: box([19, 0, 0], [10, 10, 10]) },
];
out.shallow = a.collisions(shallow, []);
out.groups = Object.fromEntries(a.rigidGroups(f.rig));
const groups = a.rigidGroups(f.rig);
out.neighbours = a.groupNeighbours(f.rig, groups);
const rigItems = ['base', 'plate', 'arm', 'tip'].map((l, i) => ({ id: l, link: groups.get(l), box: box([[0, 4, 14, 28][i], 0, 0], [10, 10, 10]) }));
out.rig_hits = a.collisions(rigItems, a.groupNeighbours(f.rig, groups));
out.points_stand = a.stabilityOfPoints([[0, 0, 0], [100, 0, 1], [100, 60, 2], [0, 60, 0], [50, 30, 90], [40, 20, 60]], [50, 30, 80]);
out.points_two = a.stabilityOfPoints([[0, 0, 0], [100, 0, 1], [50, 30, 90]], [50, 30, 80]);
process.stdout.write(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = tmp_path_factory.mktemp("js") / "run.mjs"
    script.write_text(SCRIPT % ANALYSIS_JS.as_uri(), encoding="utf-8")
    out = subprocess.run(  # noqa: S603 - node runs a script this test wrote
        [node, str(script)],
        input=json.dumps({"q45": Q45, "rig": RIG}),
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(out.stdout)


def test_oriented_boxes_overlap_when_they_share_volume_not_when_apart_or_only_touching(result):
    assert result["apart"] is False and result["touching"] is False and result["inside"] is True
    assert (
        result["turned_apart"] is False and result["turned_in"] is True
    )  # a turned box reaches further along x


def test_collisions_skip_the_same_link_and_linked_links_and_report_the_rest(result):
    # a-b share a link, b-c... c is linked to l1 (a neighbour); d (l3) overlaps a, b and c; e is far away
    assert sorted(map(sorted, result["collisions"])) == [["a", "d"], ["b", "d"], ["c", "d"]]


def test_the_centre_of_mass_is_mass_weighted_and_absent_without_mass(result):
    assert result["com"] == {"mass": 4, "p": [3, 0, 6]} and result["no_mass"] is None


def test_the_hull_and_the_inside_margin(result):
    assert sorted(map(tuple, result["hull"])) == [(0, 0), (0, 4), (4, 0), (4, 4)]
    assert result["margin_in"] == pytest.approx(5.0) and result["margin_edge"] == pytest.approx(0.0)
    assert result["margin_out"] == pytest.approx(-4.0)


def test_a_robot_stands_when_its_centre_of_mass_is_over_its_feet(result):
    s = result["stand"]
    assert s["stable"] and s["ground"] == 0 and s["height"] == 80 and s["margin"] > 20
    assert (
        result["tip"]["stable"] is False and result["tip"]["margin"] < 0
    )  # over the edge: it tips
    assert result["one_foot"]["stable"] is False  # a single support point is no polygon
    assert result["nothing"] is None


def test_the_rig_carries_link_masses_for_the_centre_of_mass():
    urdf = """<robot name="r"><link name="a"><inertial><mass value="2"/><origin xyz="0.1 0 0.2"/><inertia ixx="1" ixy="0" ixz="0" iyy="1" iyz="0" izz="1"/></inertial></link>
      <link name="b"><inertial><mass value="0"/></inertial></link><link name="c"/>
      <joint name="j" type="fixed"><parent link="a"/><child link="b"/></joint></robot>"""
    _, _, rig, _ = assemble(urdf)
    assert rig["links"] == {"a": {"mass": 2.0, "com": [100.0, 0.0, 200.0]}}


def test_a_partial_overlap_under_the_depth_threshold_is_not_a_collision_and_deep_ones_are(result):
    assert result["depth_in"] == pytest.approx(4.4) and result["depth_apart"] is True
    assert result["shallow"] == []  # 1 mm of shared volume is a touch, not a crash


def test_links_welded_by_fixed_joints_are_one_rigid_body_and_moving_joints_make_neighbours(result):
    g = result["groups"]
    assert g["base"] == g["plate"] and g["arm"] != g["base"] and g["tip"] != g["arm"]
    assert sorted(map(sorted, result["neighbours"])) == sorted(
        map(sorted, [[g["base"], g["arm"]], [g["arm"], g["tip"]]])
    )
    # base+plate overlap by design (welded), arm and tip are neighbours of the groups next to them: nothing is flagged
    assert result["rig_hits"] == []


def test_standing_is_judged_from_the_actual_lowest_points(result):
    assert result["points_stand"]["stable"] is True and result["points_stand"]["ground"] == 0
    assert (
        result["points_two"]["stable"] is False
    )  # three points, two of them at the ground: no polygon
