# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The 3D scene of a designed robot: its parts placed, its groups coloured, its BOM complete."""

from __future__ import annotations

import json
import struct

from neml_brain.evolution.model_scene import (
    GROUP_ORDER,
    ascii_stl_to_binary,
    build_scene,
    scene_name,
    stl_bounds,
)


def test_the_scene_of_a_designed_robot_has_its_parts_and_is_serialisable(generated):
    scene = build_scene("gezgin@a1", generated)
    json.dumps(scene)
    assert scene["imported"] and scene["generated"] and scene["wiring"] == []
    ids = [p["id"] for p in scene["parts"]]
    assert len(ids) == len(set(ids)) and ids
    assert all(p["group"] in GROUP_ORDER and "order" in p for p in scene["parts"])
    assert scene["parts"][0]["geom"]["type"] == "stl" and scene["parts"][0]["geom"]["url"].endswith(
        ".stl"
    )


def test_the_bom_lists_what_to_print_and_what_to_buy(generated):
    rows = {
        r["part"]: r
        for r in build_scene("g", generated)["bom"]
        if r["group"] != "İçe aktarılan (GitHub)"
    }
    printed = rows["base: gövde"]
    assert printed["group"] == "Basılı parçalar (lab tasarımı)" and "PETG" in printed["spec"]
    assert (
        rows["motor: tekerlek motoru"]["group"] == "Satın alınanlar"
        and "60 g" in rows["motor: tekerlek motoru"]["spec"]
    )


def test_a_layout_override_moves_a_part_and_marks_it(generated):
    pid = build_scene("g", generated)["parts"][0]["id"]
    generated["mechanical"]["layout"] = {pid: {"pos": [10, 20, 30]}}
    part = build_scene("g", generated)["parts"][0]
    assert part["pos"] == [10.0, 20.0, 30.0] and part["moved"]


def test_the_scene_name_is_stable_and_derivable():
    assert scene_name("a@b") == scene_name("a@b") != scene_name("a@c")
    assert scene_name("x").startswith("scene-") and scene_name("x").endswith(".json")


def test_an_ascii_stl_becomes_a_smaller_binary_one_with_the_same_bounds(tmp_path):
    source = tmp_path / "p.stl"
    source.write_text(
        "solid p\n facet normal 0 0 1\n  outer loop\n   vertex 0 0 0\n   vertex 10 0 0\n"
        "   vertex 0 20 5\n  endloop\n endfacet\nendsolid p\n"
    )
    target = ascii_stl_to_binary(source, tmp_path / "b.stl")
    assert struct.unpack("<I", target.read_bytes()[80:84])[0] == 1
    low, high = stl_bounds(target)
    assert list(low) == [0, 0, 0] and list(high) == [10, 20, 5]


def test_binary_stl_normals_are_unit_length_so_the_part_is_lit(tmp_path):
    source = tmp_path / "p.stl"
    source.write_text(
        "solid p\n facet normal 0 0 0\n  outer loop\n   vertex 0 0 0\n   vertex 10 0 0\n"
        "   vertex 0 20 0\n  endloop\n endfacet\nendsolid p\n"
    )
    data = ascii_stl_to_binary(source, tmp_path / "b.stl").read_bytes()
    nx, ny, nz = struct.unpack("<3f", data[84:96])
    assert (nx, ny, nz) == (0.0, 0.0, 1.0)
