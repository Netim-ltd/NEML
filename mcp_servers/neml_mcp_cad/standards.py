# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy. All rights reserved.
# Proprietary and confidential. Unauthorized use is prohibited.
"""Engineering standards as data: ISO 286 limits and fits, and the standard parts a mechanic never draws twice
(ISO 4762 screws, ISO 4032 nuts, ISO 7089 washers, deep-groove bearings, T-slot profiles) as CSG recipes. Pure Python."""

from __future__ import annotations

import math
import re
from typing import Any

# --- ISO 286-1: tolerance grades and fundamental deviations (micrometres), nominal size ranges 1..250 mm -------------------------------
RANGES = ((1, 3), (3, 6), (6, 10), (10, 18), (18, 30), (30, 50), (50, 80), (80, 120), (120, 180), (180, 250))
IT = {  # grade -> tolerance width per range
    5: (4, 5, 6, 8, 9, 11, 13, 15, 18, 20),
    6: (6, 8, 9, 11, 13, 16, 19, 22, 25, 29),
    7: (10, 12, 15, 18, 21, 25, 30, 35, 40, 46),
    8: (14, 18, 22, 27, 33, 39, 46, 54, 63, 72),
    9: (25, 30, 36, 43, 52, 62, 74, 87, 100, 115),
    10: (40, 48, 58, 70, 84, 100, 120, 140, 160, 185),
    11: (60, 75, 90, 110, 130, 160, 190, 220, 250, 290),
    12: (100, 120, 150, 180, 210, 250, 300, 350, 400, 460),
}
# shaft upper deviation es (letters d..h, below zero) and lower deviation ei (k, m, n, p, above zero)
SHAFT_ES = {
    "d": (-20, -30, -40, -50, -65, -80, -100, -120, -145, -170),
    "e": (-14, -20, -25, -32, -40, -50, -60, -72, -85, -100),
    "f": (-6, -10, -13, -16, -20, -25, -30, -36, -43, -50),
    "g": (-2, -4, -5, -6, -7, -9, -10, -12, -14, -15),
    "h": (0,) * 10,
}
SHAFT_EI = {
    "k": (0, 1, 1, 1, 2, 2, 2, 3, 3, 4),  # grades 4..7
    "m": (2, 4, 6, 7, 8, 9, 11, 13, 15, 17),
    "n": (4, 8, 10, 12, 15, 17, 20, 23, 27, 31),
    "p": (6, 12, 15, 18, 22, 26, 32, 37, 43, 50),
}


def _row(nominal: float) -> int:
    for i, (lo, hi) in enumerate(RANGES):
        if lo < nominal <= hi or (i == 0 and nominal == lo):
            return i
    raise ValueError("ISO 286 table covers nominal sizes 1..250 mm")


def limits(nominal: float, code: str) -> tuple[float, float]:
    """Lower and upper deviation in micrometres for a code like 'H7' (hole), 'g6' (shaft) or 'JS9'."""
    m = re.fullmatch(r"([A-Za-z]{1,2})(\d{1,2})", code.strip())
    if not m or int(m.group(2)) not in IT:
        raise ValueError(f"unknown tolerance code {code!r}; grades 5..12, letters D E F G H JS (holes), d e f g h js k m n p (shafts)")
    letter, grade, i = m.group(1), int(m.group(2)), _row(nominal)
    width = IT[grade][i]
    low = letter.lower()
    if low == "js":
        return -width / 2, width / 2
    if low in SHAFT_ES and low in ("d", "e", "f", "g", "h"):
        es = SHAFT_ES[low][i]
        if letter.isupper():  # a hole letter mirrors the shaft with the same letter: EI = -es
            return -es, -es + width
        return es - width, es
    if low in SHAFT_EI and letter.islower():
        ei = SHAFT_EI[low][i]
        return ei, ei + width
    raise ValueError(f"unknown tolerance code {code!r}")


def fit(nominal: float, hole: str = "H7", shaft: str = "g6") -> dict[str, Any]:
    """Limits of a hole/shaft pair (mm) and the resulting clearance or interference."""
    hl, hu = limits(nominal, hole)
    sl, su = limits(nominal, shaft)
    clear_min, clear_max = (hl - su) / 1000, (hu - sl) / 1000
    kind = "boşluklu" if clear_min >= 0 else "sıkı geçme" if clear_max <= 0 else "geçişli"
    return {
        "nominal": nominal,
        "hole": {"code": hole, "min": round(nominal + hl / 1000, 4), "max": round(nominal + hu / 1000, 4)},
        "shaft": {"code": shaft, "min": round(nominal + sl / 1000, 4), "max": round(nominal + su / 1000, 4)},
        "clearance_min_mm": round(clear_min, 4),
        "clearance_max_mm": round(clear_max, 4),
        "type": kind,
    }


# --- standard parts ---------------------------------------------------------------------------------------------------------------------
# size -> (head dia dk, head height k, hex socket s, socket depth t)
ISO4762 = {"M2": (3.8, 2, 1.5, 1), "M2.5": (4.5, 2.5, 2, 1.1), "M3": (5.5, 3, 2.5, 1.3), "M4": (7, 4, 3, 2), "M5": (8.5, 5, 4, 2.5), "M6": (10, 6, 5, 3), "M8": (13, 8, 6, 4), "M10": (16, 10, 8, 5), "M12": (18, 12, 10, 6)}
ISO4032 = {"M2": (4, 1.6), "M2.5": (5, 2), "M3": (5.5, 2.4), "M4": (7, 3.2), "M5": (8, 4.7), "M6": (10, 5.2), "M8": (13, 6.8), "M10": (16, 8.4), "M12": (18, 10.8)}  # across flats s, height m
ISO7089 = {"M2": (2.2, 5, 0.3), "M2.5": (2.7, 6, 0.5), "M3": (3.2, 7, 0.5), "M4": (4.3, 9, 0.8), "M5": (5.3, 10, 1), "M6": (6.4, 12, 1.6), "M8": (8.4, 16, 1.6), "M10": (10.5, 20, 2), "M12": (13, 24, 2.5)}  # bore, outer, thickness
BEARINGS = {  # designation -> bore, outer, width
    "623": (3, 10, 4), "624": (4, 13, 5), "625": (5, 16, 5), "626": (6, 19, 6), "607": (7, 19, 6), "608": (8, 22, 7), "609": (9, 24, 7),
    "6000": (10, 26, 8), "6001": (12, 28, 8), "6002": (15, 32, 9), "6003": (17, 35, 10), "6200": (10, 30, 9), "6201": (12, 32, 10), "6202": (15, 35, 11), "6203": (17, 40, 12),
}
PROFILES = {"2020": (20, 6.2, 4.2), "3030": (30, 8.2, 6.8), "4040": (40, 8.2, 8.5)}  # side, slot opening, centre bore
STEEL_G_MM3 = 0.00785


def _hex(across_flats: float) -> list[list[float]]:
    r = across_flats / math.sqrt(3)
    return [[round(r * math.cos(math.radians(60 * k)), 4), round(r * math.sin(math.radians(60 * k)), 4)] for k in range(6)]


def _cyl(i: str, r: float, h: float, z: float, x: float = 0, y: float = 0) -> dict[str, Any]:
    return {"id": i, "t": "cyl", "r": round(r, 3), "h": round(h, 3), "axis": "z", "at": [x, y, round(z, 3)]}


def standard_part(kind: str, size: str, length: float = 0.0) -> dict[str, Any]:
    """A recipe for a standard part. kind: screw (ISO 4762, length mm), nut (ISO 4032), washer (ISO 7089), bearing (designation as size), profile (2020/3030/4040, length mm)."""
    if kind == "screw":
        dk, k, s, t = ISO4762[size]
        d = float(size[1:])
        if length < d or length > 200:
            raise ValueError("screw length must be between d and 200 mm")
        recipe = {
            "solids": [_cyl("head", dk / 2, k, 0), _cyl("shank", d / 2, length + 0.01, -length),
                       {"id": "sock", "t": "prism", "plane": "xy", "at": [0, 0, k - t], "h": t + 1, "pts": _hex(s)}],
            "steps": [{"op": "fuse", "a": "head", "b": "shank", "out": "body"}, {"op": "cut", "a": "body", "b": "sock", "out": "part"}],
            "result": "part",
        }
        volume = math.pi * (dk / 2) ** 2 * k + math.pi * (d / 2) ** 2 * length
        return {"norm": f"ISO 4762 {size}x{length:g}", "recipe": recipe, "mass_g": round(volume * STEEL_G_MM3, 2)}
    if kind == "nut":
        s, m = ISO4032[size]
        d = float(size[1:])
        recipe = {
            "solids": [{"id": "body", "t": "prism", "plane": "xy", "at": [0, 0, 0], "h": m, "pts": _hex(s)}, _cyl("bore", d / 2, m + 2, -1)],
            "steps": [{"op": "cut", "a": "body", "b": "bore", "out": "part"}],
            "result": "part",
        }
        volume = math.sqrt(3) / 2 * s * s * m - math.pi * (d / 2) ** 2 * m
        return {"norm": f"ISO 4032 {size}", "recipe": recipe, "mass_g": round(volume * STEEL_G_MM3, 2)}
    if kind == "washer":
        d1, d2, h = ISO7089[size]
        recipe = {"solids": [_cyl("body", d2 / 2, h, 0), _cyl("bore", d1 / 2, h + 2, -1)], "steps": [{"op": "cut", "a": "body", "b": "bore", "out": "part"}], "result": "part"}
        return {"norm": f"ISO 7089 {size}", "recipe": recipe, "mass_g": round(math.pi * ((d2 / 2) ** 2 - (d1 / 2) ** 2) * h * STEEL_G_MM3, 2)}
    if kind == "bearing":
        d, outer, w = BEARINGS[size]
        recipe = {"solids": [_cyl("body", outer / 2, w, 0), _cyl("bore", d / 2, w + 2, -1)], "steps": [{"op": "cut", "a": "body", "b": "bore", "out": "part"}], "result": "part"}
        return {"norm": f"Rulman {size} ({d}x{outer}x{w})", "recipe": recipe, "mass_g": round(math.pi * ((outer / 2) ** 2 - (d / 2) ** 2) * w * STEEL_G_MM3 * 0.6, 2)}
    if kind == "profile":
        side, slot, bore = PROFILES[size]
        if not 10 <= length <= 600:
            raise ValueError("profile length must be between 10 and 600 mm")
        half, depth = side / 2, side * 0.3
        cuts = [_cyl("bore", bore / 2, length + 2, -1, half, half)]
        for n, (x0, y0, w, h) in enumerate(((half - slot / 2, side - depth, slot, depth + 1), (half - slot / 2, -1, slot, depth + 1), (side - depth, half - slot / 2, depth + 1, slot), (-1, half - slot / 2, depth + 1, slot))):
            cuts.append({"id": f"slot{n}", "t": "box", "at": [round(x0, 3), round(y0, 3), -1], "size": [round(w, 3), round(h, 3), length + 2]})
        steps, last = [], "body"
        for n, c in enumerate(cuts):
            steps.append({"op": "cut", "a": last, "b": c["id"], "out": f"c{n}"})
            last = f"c{n}"
        body = {"id": "body", "t": "box", "at": [0, 0, 0], "size": [side, side, length]}
        return {"norm": f"Alüminyum profil {size} x {length:g}", "recipe": {"solids": [body, *cuts], "steps": steps, "result": last}, "mass_g": round(side * side * 0.45 * length * 0.0027, 2)}
    raise ValueError("kind must be screw, nut, washer, bearing or profile")
