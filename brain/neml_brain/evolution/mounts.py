# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Screw holes where the bought parts sit on a designed part.

The model draws the chassis; the board, battery, motors and sensors the plan puts on it need somewhere to be screwed down. Those
holes are not left to the model's memory: from the plan (where each bought child sits, how big it is) and the built part's own
bounding box, this module adds plain 3.2 mm holes under every child that rests on the top or bottom face.

# ponytail: one pattern per kind (4 corner holes for boards and batteries, 2 end holes for motors and servos), the face is the first
of top/bottom, then x, then y that the child touches; the holes ignore the part's inner pockets."""

from __future__ import annotations

from typing import Any

from neml_brain.evolution.catalog import CATALOG

HOLE_D = 3.2
INSET = 3.5  # hole centre from the bought part's edge, mm
DEPTH = 4.0  # blind depth; a thinner part gets through holes
MAX_FEATURES = 12  # the recipe schema's limit
TOUCH = 3.0  # a child within this of a face rests on it, mm
MOUNTED = {"board", "driver", "regulator", "sensor", "battery", "dc_motor", "servo", "switch"}


def _pattern(kind: str, a: float, b: float) -> list[tuple[float, float]]:
    """Hole offsets from the child's centre in the face plane, `a` x `b` mm."""
    ha, hb = a / 2 - INSET, b / 2 - INSET
    if ha <= 0 or hb <= 0:
        return []
    if kind in ("dc_motor", "servo"):  # two holes at the ends of the long side
        return [(-ha, 0.0), (ha, 0.0)] if a >= b else [(0.0, -hb), (0.0, hb)]
    return [(-ha, -hb), (ha, -hb), (-ha, hb), (ha, hb)]


def mount_features(plan: dict[str, Any], link: dict[str, Any], bbox: list[float]) -> list[dict[str, Any]]:
    """Hole features (recipe `features`) for the bought parts that rest on a face of `link`; `bbox` is the built part [x0, y0, z0, x1, y1, z1] in its own frame."""
    from neml_brain.evolution.generative import layout, slug

    centre, size, parent = layout(plan)
    me = slug(str(link["name"]))
    lo, hi = bbox[:3], bbox[3:]
    out: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for child in plan["links"]:
        n = slug(str(child["name"]))
        part = CATALOG.get(str(child.get("part", "")))
        if parent.get(n) != me or child["source"] != "bought" or part is None or part["kind"] not in MOUNTED:
            continue
        rel = [centre[n][k] - centre[me][k] for k in range(3)]
        half = [v / 2 for v in size[n]]
        for k in (2, 0, 1):  # a child rests on the top/bottom face, else on a side face
            if rel[k] - half[k] >= hi[k] - TOUCH:
                face, sign, at_k = "+", "-", hi[k]  # child on the + face: drill from the face into the part
            elif rel[k] + half[k] <= lo[k] + TOUCH:
                face, sign, at_k = "-", "+", lo[k]
            else:
                continue
            u, v = [j for j in range(3) if j != k]
            for du, dv in _pattern(part["kind"], size[n][u], size[n][v]):
                pos = [0.0, 0.0, 0.0]
                pos[k], pos[u], pos[v] = at_k, rel[u] + du, rel[v] + dv
                if not all(lo[j] + 1.5 <= pos[j] <= hi[j] - 1.5 for j in (u, v)) or (k, face, round(pos[u]), round(pos[v])) in seen:
                    continue
                seen.add((k, face, round(pos[u]), round(pos[v])))
                hole: dict[str, Any] = {"f": "hole", "kind": "plain", "at": [round(c, 2) for c in pos], "axis": "xyz"[k], "dir": sign, "d": HOLE_D}
                if hi[k] - lo[k] > DEPTH + 1.5:
                    hole["depth"] = DEPTH
                out.append(hole)
            break
    return out[:MAX_FEATURES]
