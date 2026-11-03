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
