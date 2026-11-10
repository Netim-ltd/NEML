# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

from neml_brain.evolution.judges import equip
from neml_brain.evolution.package import package

from .test_generative import PLAN


def test_a_designed_robot_gets_a_bill_of_materials_a_wiring_graph_and_ordered_steps():
    pk = package(equip(PLAN))
    ids = {p["id"] for p in pk["parts"]}
    assert "tt_wheel" in ids and any(i.startswith("baski:") for i in ids)
    assert next(p for p in pk["parts"] if p["id"] == "tt_wheel")["qty"] == 2
    kinds = {n["kind"] for n in pk["wiring"]["nodes"]}
    assert {"battery", "board", "driver", "dc_motor"} <= kinds
    assert all(e["from"] in {n["id"] for n in pk["wiring"]["nodes"]} and e["type"] in {"power", "data"} for e in pk["wiring"]["edges"])
    phases = [s["phase"] for s in pk["steps"]]
    assert phases.index("baski") < phases.index("montaj") < phases.index("kablolama") < phases.index("test")
    assert pk["totals"]["price"] is None and pk["totals"]["mass_g"] > 0


def test_generated_rows_read_the_whole_stored_plan():
    from neml_brain.evolution.model_scene import generated_rows

    plan = {"links": [{"name": "govde", "source": "designed", "material": "PETG", "dims_mm": [100, 80, 30], "role": "gövde"}]}
    rows = generated_rows({"mechanical": {"generated": {"plan": plan}, "imports": []}})
    assert [r["part"] for r in rows] == ["govde: gövde"]


def test_a_designed_part_is_centred_on_its_link_origin_in_the_preview_like_in_the_simulation(tmp_path):
    import numpy as np

    from neml_brain.evolution.generative import centre_stl
    from neml_brain.evolution.mesh_formats import stl_triangles, write_stl

    cube = np.array([[[0, 0, 0], [10, 0, 0], [0, 20, 0]], [[0, 0, 30], [10, 0, 30], [0, 20, 30]]], dtype=float)
    path = write_stl(cube, tmp_path / "a.stl")
    centre_stl(path)
    pts = stl_triangles(path).reshape(-1, 3)
    assert np.allclose((pts.min(0) + pts.max(0)) / 2, 0, atol=0.01)
