# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy. All rights reserved.
# Proprietary and confidential. Unauthorized use is prohibited.
"""Assembly mates on bounding boxes: parts are placed by constraints instead of by guessed coordinates. Pure Python.

mates (b is moved, a stays), each touching only the axes it names, applied in order:
  stack   {a, b, axis, gap?, align?}     b sits on the + side of a along `axis` with `gap` mm between; centred on the other axes unless align is false
  flush   {a, b, axis, side}             b's min (or max) face on `axis` is level with a's
  align   {a, b, axes, mode?}            centres (mode center, default) or min/max faces equal on the listed axes
  offset  {a, b, d}                      b's min corner is a's min corner plus d = [dx, dy, dz]
  fixed   {a, at}                        a's min corner goes to `at` (otherwise the first part stays where it was modelled)
# ponytail: box-based mates, not face/axis mates; a bore-to-shaft concentric mate is `align` on the two radial axes."""

from __future__ import annotations

import math
from typing import Any

AX = {"x": 0, "y": 1, "z": 2}


def _rot(p: list[float], rot: list[float]) -> list[float]:
    x, y, z = p
    for axis, ang in zip("xyz", rot, strict=True):
        c, s = round(math.cos(math.radians(ang))), round(math.sin(math.radians(ang)))
        if axis == "x":
            y, z = y * c - z * s, y * s + z * c
        elif axis == "y":
            x, z = x * c + z * s, -x * s + z * c
        else:
            x, y = x * c - y * s, x * s + y * c
    return [x, y, z]


def turned_box(bbox: list[float], rot: list[float]) -> list[float]:
    """Bounding box of a part after turning it by multiples of 90 degrees about x, then y, then z."""
    corners = [_rot([bbox[i], bbox[1 + j], bbox[2 + k]], rot) for i in (0, 3) for j in (0, 3) for k in (0, 3)]
    return [min(c[i] for c in corners) for i in range(3)] + [max(c[i] for c in corners) for i in range(3)]


def solve(parts: dict[str, dict[str, Any]], mates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """parts {id: {bbox, rot?}} (bbox as modelled) -> {id: {place: [x, y, z], rot, bbox}} where `place` is the translation to apply after turning."""
    box = {i: turned_box(p["bbox"], p.get("rot") or [0, 0, 0]) for i, p in parts.items()}
    place = {i: [0.0, 0.0, 0.0] for i in parts}

    def lo(i: str, a: int) -> float:
        return box[i][a] + place[i][a]

    def hi(i: str, a: int) -> float:
        return box[i][3 + a] + place[i][a]

    for m in mates:
        op, a, b = m.get("op"), m.get("a"), m.get("b")
        for i in (a, b) if op != "fixed" else (a,):
            if i not in parts:
                raise ValueError(f"mate names an unknown part: {i}")
        if op == "fixed":
            for k in range(3):
                place[a][k] += m["at"][k] - lo(a, k)
        elif op == "stack":
            ax = AX[m["axis"]]
            place[b][ax] += hi(a, ax) + float(m.get("gap", 0)) - lo(b, ax)
            if m.get("align", True):
                for k in range(3):
                    if k != ax:
                        place[b][k] += (lo(a, k) + hi(a, k)) / 2 - (lo(b, k) + hi(b, k)) / 2
        elif op == "flush":
            ax = AX[m["axis"]]
            place[b][ax] += (lo(a, ax) - lo(b, ax)) if m.get("side", "min") == "min" else (hi(a, ax) - hi(b, ax))
        elif op == "align":
            for name in m["axes"]:
                ax = AX[name]
                mode = m.get("mode", "center")
                src = lo(a, ax) if mode == "min" else hi(a, ax) if mode == "max" else (lo(a, ax) + hi(a, ax)) / 2
                dst = lo(b, ax) if mode == "min" else hi(b, ax) if mode == "max" else (lo(b, ax) + hi(b, ax)) / 2
                place[b][ax] += src - dst
        elif op == "offset":
            for k in range(3):
                place[b][k] += lo(a, k) + m["d"][k] - lo(b, k)
        else:
            raise ValueError(f"unknown mate {op!r}: stack, flush, align, offset or fixed")
    return {i: {"place": [round(v, 4) for v in place[i]], "rot": parts[i].get("rot") or [0, 0, 0], "bbox": [round(box[i][k] + place[i][k % 3], 4) for k in range(6)]} for i in parts}
