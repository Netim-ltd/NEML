# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
# ruff: noqa: E501
"""A number for how well a robot plan would do its job, from physics the lab already knows, before anything is built.

The old plan score clipped the tip margin at 2, so three different plans all got 1.68 and the "race" between them was a coin toss.
This one measures what the simulation worlds ask for: a 10 degree ramp (motor torque over the torque the slope needs), a low obstacle
(wheel radius), ground clearance, tipping, and then weight. Every term is capped so one great number cannot hide a bad one.
# ponytail: static estimates (no motor curves, no slip); the world model's kNN takes over once it has enough runs."""

from __future__ import annotations

import math
from typing import Any

STEP_MM = 30.0  # the low-obstacle world's step: a wheel climbs about 0.8 of its radius
RAMP_DEG = 10.0
SLOPE_SAFETY = 1.5


def mission_score(plan: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    """(score, facts): higher is better. A plan the simulation cannot drive scores far below any drivable one."""
    from neml_brain.evolution.generative import tip_margin
    from neml_brain.evolution.judges import _loads
    from neml_brain.evolution.robot_sdf import NotDrivable, sdf_of

    tip = tip_margin(plan)
    try:
        _, facts = sdf_of(plan)
    except NotDrivable:
        return -10.0 + min(tip, 2.0), {"drivable": False, "tip_margin": round(tip, 2)}
    _, kinds, wheels, _arms = _loads(plan)
    motors = sorted((p["torque_kgcm"] for p in kinds.get("dc_motor", [])), reverse=True)[: max(len(wheels), 1)]
    r_cm = facts["wheel_radius_mm"] / 10
    need = facts["mass_kg"] * math.sin(math.radians(RAMP_DEG)) * r_cm / max(len(wheels), 1)  # kg*cm per driven wheel to hold the slope
    have = min(motors) if len(motors) >= len(wheels) and motors else 0.0
    slope = min(have / (SLOPE_SAFETY * max(need, 1e-6)), 2.0)  # 1 = the motor holds the ramp with the safety factor
    step = min(0.8 * facts["wheel_radius_mm"] / STEP_MM, 2.0)  # 1 = the wheel climbs the obstacle
    ground = min(facts["clearance_mm"] / 15.0, 1.0)
    stable = min(tip / 1.0, 2.0)
    light = 1.0 / (1.0 + facts["mass_kg"])  # between 0 and 1, never decides alone
    score = 2.0 * slope + 2.0 * step + 1.0 * ground + 1.5 * stable + 1.0 * light - 0.02 * len(plan["links"])
    info = {"drivable": True, "slope": round(slope, 2), "step": round(step, 2), "ground": round(ground, 2), "tip_margin": round(tip, 2), "mass_kg": facts["mass_kg"]}
    return score, info
