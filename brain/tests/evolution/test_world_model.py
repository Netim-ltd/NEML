# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

from neml_brain.evolution.world_model import MIN_RUNS, WorldModel


def facts(track: float, com: float) -> dict[str, float]:
    return {"track_mm": track, "base_mm": 200, "wheel_radius_mm": 32, "mass_kg": 1.0, "com_mm": com}


def test_no_opinion_without_enough_runs(tmp_path):
    wm = WorldModel(tmp_path)
    wm.log(facts(150, 40), "flat", 3.0, False)
    assert wm.predict(facts(150, 40)) is None


def test_similar_robots_that_tipped_predict_a_tip(tmp_path):
    wm = WorldModel(tmp_path)
    for i in range(MIN_RUNS):  # narrow and tall tips, wide and low drives
        wm.log(facts(60 + i, 150), "ramp", 0.1, True)
        wm.log(facts(200 + i, 40), "ramp", 3.0, False)
    narrow, wide = wm.predict(facts(65, 148)), wm.predict(facts(205, 42))
    assert narrow["p_tip"] == 1.0
    assert wide["p_tip"] == 0.0 and wide["x_m"] > 2.5
