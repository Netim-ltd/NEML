# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bought parts with real, fixed numbers, so the model chooses from a list instead of inventing a servo.

Numbers are the typical datasheet / shop values of widely sold parts (body size in mm, mass in g, torque in kg*cm at about
5-6 V). Every entry is `verified: False` until the owner has checked it against the part in hand or its datasheet; prices are
left empty on purpose (the shop pages are read at ordering time). The list is plain data and grows by adding rows."""

from __future__ import annotations

from typing import Any

# kind: servo | dc_motor | wheel | battery | board | driver | regulator | sensor | switch
_ROWS: list[tuple[str, str, str, list[float], float, dict[str, Any]]] = [
    ("sg90", "servo", "SG90 mikro servo", [22.5, 12.2, 22.7], 9, {"torque_kgcm": 1.8, "volt": "4.8-6"}),
    ("mg90s", "servo", "MG90S metal dişli mikro servo", [22.8, 12.4, 28.5], 13.4, {"torque_kgcm": 2.2, "volt": "4.8-6"}),
    ("mg996r", "servo", "MG996R metal dişli servo", [40.7, 19.7, 42.9], 55, {"torque_kgcm": 9.4, "volt": "4.8-6"}),
    ("ds3218", "servo", "DS3218 20 kg servo", [40, 20, 40.5], 60, {"torque_kgcm": 18, "volt": "6-7.4"}),
    ("tt_motor", "dc_motor", "TT sarı redüktörlü motor 1:48", [70, 22, 18], 30, {"torque_kgcm": 0.8, "volt": "3-6"}),
    ("n20_motor", "dc_motor", "N20 redüktörlü mikro motor", [28, 12, 10], 10, {"torque_kgcm": 1.0, "volt": "6"}),
    ("jga25_motor", "dc_motor", "JGA25-370 redüktörlü motor", [46, 25, 25], 75, {"torque_kgcm": 4.0, "volt": "12"}),
    ("tt_wheel", "wheel", "TT motor tekeri 65 mm", [65, 65, 26], 25, {}),
    ("cell_18650", "battery", "18650 Li-ion hücre 3.7 V 2600 mAh", [18.5, 18.5, 65], 47, {"volt": "3.7", "mah": 2600}),
    ("lipo_3s_2200", "battery", "3S LiPo 11.1 V 2200 mAh", [105, 35, 25], 185, {"volt": "11.1", "mah": 2200}),
    ("esp32_devkit", "board", "ESP32 DevKit (30 pin)", [51.5, 28.5, 12], 10, {"io": "wifi+bt"}),
    ("arduino_nano", "board", "Arduino Nano", [45, 18, 18], 7, {}),
    ("rpi_zero_2w", "board", "Raspberry Pi Zero 2 W", [65, 30, 5], 10, {}),
    ("pca9685", "driver", "PCA9685 16 kanal servo sürücü", [62.5, 25.4, 10], 10, {"channels": 16}),
    ("tb6612", "driver", "TB6612FNG çift motor sürücü modülü", [20, 20, 5], 3, {"channels": 2}),
    ("l298n", "driver", "L298N çift motor sürücü modülü", [43, 43, 27], 30, {"channels": 2}),
    ("buck_lm2596", "regulator", "LM2596 ayarlı düşürücü", [43, 21, 14], 10, {}),
    ("mpu6050", "sensor", "MPU6050 IMU modülü", [21, 16, 3], 2, {}),
    ("hc_sr04", "sensor", "HC-SR04 ultrasonik mesafe sensörü", [45, 20, 15], 9, {}),
    ("estop_22mm", "switch", "22 mm acil durdurma düğmesi (mantar)", [40, 40, 50], 40, {}),
    ("rocker_switch", "switch", "Kayar/rocker ana şalter", [21, 15, 25], 5, {}),
]

CATALOG: dict[str, dict[str, Any]] = {
    pid: {"id": pid, "kind": kind, "name": name, "dims_mm": dims, "mass_g": mass, "verified": False, **spec}
    for pid, kind, name, dims, mass, spec in _ROWS
}
OTHER = "diger"  # a bought part the list does not have: allowed in a plan, but it blocks activation until it is added


def listing() -> str:
    """The catalog as prompt lines: id, name, size, mass and torque."""
    lines = []
    for p in CATALOG.values():
        extra = f", {p['torque_kgcm']} kg*cm" if "torque_kgcm" in p else ""
        lines.append(f"{p['id']} ({p['kind']}): {p['name']}, {'x'.join(f'{v:g}' for v in p['dims_mm'])} mm, {p['mass_g']:g} g{extra}")
    return "\n".join(lines)


def apply(plan: dict[str, Any]) -> dict[str, Any]:
    """A bought link that names a catalog part takes that part's real size and mass (the model's guess is replaced)."""
    for lk in plan["links"]:
        part = CATALOG.get(str(lk.get("part", "")))
        if lk.get("source") == "bought" and part:
            lk["dims_mm"], lk["mass_g"] = list(part["dims_mm"]), part["mass_g"]
    return plan
