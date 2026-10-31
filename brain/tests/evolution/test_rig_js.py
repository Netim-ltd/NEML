# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The viewer's forward kinematics (rig.js) must agree with the lab's (urdf_assembly.link_matrices)."""

from __future__ import annotations

import json
import shutil
import subprocess

import numpy as np
import pytest

from neml_brain.evolution.urdf_assembly import assemble, link_matrices
from neml_brain.paths import REPO_ROOT

RIG_JS = REPO_ROOT / "dotnet" / "Neml.Web" / "wwwroot" / "js" / "rig.js"
URDF = """<robot name="r">
  <link name="base"/><link name="a"/><link name="b"/><link name="c"/><link name="d"/>
  <joint name="j1" type="revolute"><parent link="base"/><child link="a"/><origin xyz="0.1 0.2 0.3" rpy="0.3 -0.2 0.5"/>
    <axis xyz="0 1 1"/><limit lower="-3" upper="3"/></joint>
  <joint name="j2" type="continuous"><parent link="a"/><child link="b"/><origin xyz="0 0 0.2" rpy="0 1.2 0"/><axis xyz="1 0 0"/></joint>
  <joint name="j3" type="prismatic"><parent link="b"/><child link="c"/><origin xyz="0.05 0 0"/><axis xyz="0 0 1"/><limit lower="0" upper="0.3"/></joint>
  <joint name="j4" type="revolute"><parent link="a"/><child link="d"/><origin xyz="0 0.1 0"/><axis xyz="0 0 1"/><limit lower="-3" upper="3"/>
    <mimic joint="j1" multiplier="-0.5" offset="0.25"/></joint>
</robot>"""
VALUES = {"j1": 0.7, "j2": -1.3, "j3": 0.12}

SCRIPT = """
import { linkMatrices, partMatrix, movable } from %r;
let text = '';
for await (const chunk of process.stdin) text += chunk;
const { rig, values, local } = JSON.parse(text);
const worlds = linkMatrices(rig, values);
process.stdout.write(JSON.stringify({
  links: Object.fromEntries(worlds),
  part: partMatrix(worlds.get('c'), local),
  movable: movable(rig).map((j) => j.name),
}));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_viewers_forward_kinematics_agrees_with_the_labs(tmp_path):
    _, _, rig, _ = assemble(URDF)
    script = tmp_path / "run.mjs"
    script.write_text(SCRIPT % RIG_JS.as_uri(), encoding="utf-8")
    local = {"pos": [1.0, 2.0, 3.0], "quat": [0.0, 0.0, float(np.sqrt(0.5)), float(np.sqrt(0.5))]}
    out = subprocess.run(  # noqa: S603 - node runs a script this test wrote
        [shutil.which("node"), str(script)],
        input=json.dumps({"rig": rig, "values": VALUES, "local": local}),
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    got = json.loads(out.stdout)
    expected = link_matrices(rig, VALUES)
    assert set(got["links"]) == set(expected)
    for name, matrix in expected.items():
        assert np.allclose(np.array(got["links"][name]).reshape(4, 4), matrix, atol=1e-6), name
    local_matrix = np.eye(4)
    local_matrix[:3, :3] = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]  # the 90 degree yaw of `local.quat`
    local_matrix[:3, 3] = local["pos"]
    assert np.allclose(np.array(got["part"]).reshape(4, 4), expected["c"] @ local_matrix, atol=1e-6)
    assert got["movable"] == ["j1", "j2", "j3"]  # j4 follows j1: not offered as a slider
    assert not np.allclose(
        expected["c"], link_matrices(rig)["c"]
    )  # the pose really moved something
