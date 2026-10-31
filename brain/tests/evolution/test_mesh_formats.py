# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Collada, PLY and the viewer's compact mesh: read as numbers, nothing executed."""

from __future__ import annotations

import struct

import numpy as np
import pytest

from neml_brain.evolution.mesh_formats import (
    MeshError,
    compact,
    dae_triangles,
    expand,
    ply_triangles,
    stl_triangles,
    write_stl,
)

DAE = """<?xml version="1.0"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
  <asset><unit name="millimeter" meter="0.001"/><up_axis>Y_UP</up_axis></asset>
  <library_geometries>
    <geometry id="g1"><mesh>
      <source id="pos"><float_array id="pa" count="12">0 0 0  10 0 0  10 10 0  0 10 0</float_array>
        <technique_common><accessor source="#pa" count="4" stride="3"/></technique_common></source>
      <vertices id="v"><input semantic="POSITION" source="#pos"/></vertices>
      <polylist count="1"><input semantic="VERTEX" source="#v" offset="0"/><vcount>4</vcount><p>0 1 2 3</p></polylist>
    </mesh></geometry>
    <geometry id="g2"><mesh>
      <source id="pos2"><float_array id="pb" count="9">0 0 0  1 0 0  0 1 0</float_array>
        <technique_common><accessor source="#pb" count="3" stride="3"/></technique_common></source>
      <vertices id="v2"><input semantic="POSITION" source="#pos2"/></vertices>
      <triangles count="1"><input semantic="VERTEX" source="#v2" offset="0"/><p>0 1 2</p></triangles>
    </mesh></geometry>
  </library_geometries>
  <library_visual_scenes><visual_scene id="s">
    <node><translate>100 0 0</translate><instance_geometry url="#g1"/></node>
    <node><matrix>1 0 0 0  0 1 0 5  0 0 1 0  0 0 0 1</matrix><node><instance_geometry url="#g2"/></node></node>
  </visual_scene></library_visual_scenes>
</COLLADA>"""


def test_a_collada_file_is_placed_by_its_scene_and_given_metres_and_z_up(tmp_path):
    path = tmp_path / "m.dae"
    path.write_text(DAE, encoding="utf-8")
    tri = dae_triangles(path)
    assert tri.shape == (3, 3, 3)  # the quad fanned into two triangles, plus one
    lo, hi = tri.reshape(-1, 3).min(axis=0), tri.reshape(-1, 3).max(axis=0)
    # millimetres to metres; Y_UP -> Z_UP turns (x, y, z) into (x, -z, y): the flat 10 mm square stands up along x and z
    assert np.allclose(lo, [0.0, 0.0, 0.0]) and np.allclose(hi, [0.11, 0.0, 0.01])


def test_collada_refuses_entities_and_other_documents(tmp_path):
    for body in ('<!DOCTYPE c [<!ENTITY a "x">]><COLLADA/>', "<notcollada/>", "<COLLADA"):
        path = tmp_path / "bad.dae"
        path.write_text(body, encoding="utf-8")
        with pytest.raises(MeshError):
            dae_triangles(path)


def test_ply_ascii_and_binary_give_the_same_fanned_triangles(tmp_path):
    ascii_ply = tmp_path / "a.ply"
    ascii_ply.write_text(
        "ply\nformat ascii 1.0\nelement vertex 4\nproperty float x\nproperty float y\nproperty float z\nelement face 1\nproperty list uchar int vertex_indices\nend_header\n0 0 0\n1 0 0\n1 1 0\n0 1 0\n4 0 1 2 3\n",
        encoding="utf-8",
    )
    head = b"ply\nformat binary_little_endian 1.0\nelement vertex 4\nproperty float x\nproperty float y\nproperty float z\nelement face 1\nproperty list uchar int vertex_indices\nend_header\n"
    body = struct.pack("<12f", 0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0) + struct.pack(
        "<B4i", 4, 0, 1, 2, 3
    )
    binary_ply = tmp_path / "b.ply"
    binary_ply.write_bytes(head + body)
    a, b = ply_triangles(ascii_ply), ply_triangles(binary_ply)
    assert a.shape == (2, 3, 3) and np.allclose(a, b)
    bad = tmp_path / "c.ply"
    bad.write_bytes(head.replace(b"binary_little_endian", b"binary_big_endian") + body)
    with pytest.raises(MeshError, match="not supported"):
        ply_triangles(bad)


def test_the_compact_viewer_mesh_is_small_and_loses_less_than_a_grid_step(tmp_path):
    rng = np.random.default_rng(1)
    base = rng.random((2000, 3)) * [300, 100, 40]
    idx = rng.integers(0, 2000, size=(6000, 3))
    tri = base[idx]
    stl = write_stl(tri, tmp_path / "t.stl")
    data = compact(stl_triangles(stl))
    assert len(data) < stl.stat().st_size / 3
    back = expand(data)
    assert back.shape == tri.shape and np.abs(back - tri).max() < 300 / 65535 * 1.01 + 1e-3
    assert expand(compact(tri[:1])).shape == (1, 3, 3)
    with pytest.raises(MeshError):
        expand(b"nope")


def test_the_viewers_nmesh_decoder_reads_what_the_lab_writes(tmp_path):
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    from neml_brain.paths import REPO_ROOT

    rng = np.random.default_rng(3)
    tri = (rng.random((6000, 3)) * [200, 80, 30])[rng.integers(0, 6000, size=(4000, 3))]
    data = compact(tri)
    (tmp_path / "m.nmesh").write_bytes(data)
    js = (REPO_ROOT / "dotnet" / "Neml.Web" / "wwwroot" / "js" / "nmesh.js").as_uri()
    script = tmp_path / "run.mjs"
    script.write_text(
        f"import {{ decode }} from {js!r};\nimport {{ readFileSync }} from 'node:fs';\n"
        "const b = readFileSync(process.argv[2]);\n"
        "const m = decode(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength));\n"
        "process.stdout.write(JSON.stringify({ positions: Array.from(m.positions), indices: Array.from(m.indices) }));\n",
        encoding="utf-8",
    )
    out = subprocess.run(  # noqa: S603 - node runs a script this test wrote
        [node, str(script), str(tmp_path / "m.nmesh")],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )  # noqa: S603
    got = json.loads(out.stdout)
    rebuilt = np.array(got["positions"]).reshape(-1, 3)[np.array(got["indices"])].reshape(-1, 3, 3)
    assert np.allclose(rebuilt, expand(data), atol=1e-3)
