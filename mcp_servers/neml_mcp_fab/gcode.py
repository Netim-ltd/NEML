# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""G-code analyser for validate_gcode (SPEC 6.4).

Reads what PrusaSlicer writes: time, filament (g/mm), layer count, max
temperature, retraction count, bridge lengths and support volume, plus the cost
`estimate` quotes. Pure text parsing - no PrusaSlicer code is linked or
embedded (SPEC 1.3).
"""

from __future__ import annotations

import math
import re

FILAMENT_DIAMETER_MM = 1.75

_TIME_RE = re.compile(r";\s*estimated printing time \(normal mode\)\s*=\s*(.+)")
_GRAM_RE = re.compile(r";\s*filament used \[g\]\s*=\s*([\d.]+)")
_MM_RE = re.compile(r";\s*filament used \[mm\]\s*=\s*([\d.]+)")
_LAYERS_RE = re.compile(r";\s*total layers count\s*=\s*(\d+)")
# PrusaSlicer prices the spool from the profile's `filament_cost` (TRY/kg here),
# so this is per-material where a single lab-wide TRY/g constant is not.
_COST_RE = re.compile(r";\s*filament cost\s*=\s*([\d.]+)")
_DIAM_RE = re.compile(r";\s*filament_diameter\s*=\s*([\d.]+)")
_DURATION_RE = re.compile(r"(\d+)\s*([dhms])")


def _hours(text: str) -> float:
    factor = {"d": 24.0, "h": 1.0, "m": 1 / 60, "s": 1 / 3600}
    return sum(int(n) * factor[u] for n, u in _DURATION_RE.findall(text.strip()))


def _word(line: str, letter: str) -> float | None:
    match = re.search(rf"(?:^|\s){letter}(-?[\d.]+)", line)
    return float(match.group(1)) if match else None


def parse(text: str) -> dict[str, float | int]:
    """Return the GcodeReport fields SPEC 6.4 lists, in SI-ish print units."""
    time_h = filament_g = filament_mm = cost = 0.0
    layer_count = layer_changes = retractions = 0
    max_temp_c = max_bed_temp_c = max_bridge_mm = support_volume_mm3 = 0.0
    diameter = FILAMENT_DIAMETER_MM
    relative_e = False
    x = y = last_e = 0.0
    section = ""

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(";"):
            if line.startswith(";TYPE:"):
                section = line[6:].strip().lower()
            elif line.startswith(";LAYER_CHANGE"):
                layer_changes += 1
            elif m := _TIME_RE.match(line):
                time_h = _hours(m.group(1))
            elif m := _GRAM_RE.match(line):
                filament_g = float(m.group(1))
            elif m := _MM_RE.match(line):
                filament_mm = float(m.group(1))
            elif m := _LAYERS_RE.match(line):
                layer_count = int(m.group(1))
            elif m := _COST_RE.match(line):
                cost = float(m.group(1))
            elif m := _DIAM_RE.match(line):
                diameter = float(m.group(1))
            continue

        code = line.split()[0].upper()
        if code in ("M104", "M109"):
            temp = _word(line, "S")
            if temp:
                max_temp_c = max(max_temp_c, temp)
            continue
        if code in ("M140", "M190"):
            bed = _word(line, "S")
            if bed:
                max_bed_temp_c = max(max_bed_temp_c, bed)
            continue
        if code == "M82":
            relative_e = False
            continue
        if code == "M83":
            relative_e = True
            continue
        if code == "G92":
            e = _word(line, "E")
            if e is not None:
                last_e = e
            continue
        if code not in ("G0", "G1"):
            continue

        nx, ny, e = _word(line, "X"), _word(line, "Y"), _word(line, "E")
        delta_e = 0.0
        if e is not None:
            delta_e = e if relative_e else e - last_e
            last_e = e if not relative_e else last_e
        moved = 0.0
        if nx is not None or ny is not None:
            tx, ty = (nx if nx is not None else x), (ny if ny is not None else y)
            moved = math.hypot(tx - x, ty - y)
            x, y = tx, ty
        if delta_e < 0 and moved == 0:
            retractions += 1
        elif delta_e > 0:
            if "bridge" in section:
                max_bridge_mm = max(max_bridge_mm, moved)
            if "support" in section:
                support_volume_mm3 += delta_e * math.pi * (diameter / 2) ** 2

    return {
        "time_h": round(time_h, 4),
        "filament_g": filament_g,
        "filament_mm": filament_mm,
        "layer_count": layer_count or layer_changes,
        "max_temp_c": max_temp_c,  # hotend (M104/M109); the bed is reported separately
        "max_bed_temp_c": max_bed_temp_c,
        "retractions": retractions,
        "max_bridge_mm": round(max_bridge_mm, 3),
        "support_volume_mm3": round(support_volume_mm3, 3),
        "cost_try": cost,  # 0.0 when the slicer declared none; estimate() falls back
    }
