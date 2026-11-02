# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Screw holes where the bought parts sit on a designed part.

The model draws the chassis; the board, battery, motors and sensors the plan puts on it need somewhere to be screwed down. Those
holes are not left to the model's memory: from the plan (where each bought child sits, how big it is) and the built part's own
bounding box, this module adds plain 3.2 mm holes under every child that rests on the top or bottom face.

# ponytail: top and bottom faces only, one pattern per kind (4 corner holes for boards and batteries, 2 end holes for motors and
servos); a side-mounted part gets nothing, and the holes ignore the part's inner pockets."""

from __future__ import annotations

from typing import Any

from neml_brain.evolution.catalog import CATALOG

HOLE_D = 3.2
INSET = 3.5  # hole centre from the bought part's edge, mm
DEPTH = 4.0  # blind depth; a thinner part gets through holes
MAX_FEATURES = 12  # the recipe schema's limit
TOUCH = 3.0  # a child within this of a face rests on it, mm
MOUNTED = {"board", "driver", "regulator", "sensor", "battery", "dc_motor", "servo", "switch"}


def _pattern(kind: str, size: list[float]) -> list[tuple[float, float]]:
    """Hole offsets from the child's centre (x, y)."""
    hx, hy = size[0] / 2 - INSET, size[1] / 2 - INSET
    if hx <= 0 or hy <= 0:
        return []
    if kind in ("dc_motor", "servo"):  # two holes at the ends of the long side
        return [(-hx, 0.0), (hx, 0.0)] if size[0] >= size[1] else [(0.0, -hy), (0.0, hy)]
    return [(-hx, -hy), (hx, -hy), (-hx, hy), (hx, hy)]


def mount_features(plan: dict[str, Any], link: dict[str, Any], bbox: list[float]) -> list[dict[str, Any]]:
    """Hole features (recipe `features`) for the bought parts that rest on `link`; `bbox` is the built part [x0, y0, z0, x1, y1, z1] in its own frame."""
    from neml_brain.evolution.generative import layout, slug

    centre, size, parent = layout(plan)
    me = slug(str(link["name"]))
    x0, y0, z0, x1, y1, z1 = bbox
    out: list[dict[str, Any]] = []
    seen: set[tuple[float, float, str]] = set()
    for child in plan["links"]:
        n = slug(str(child["name"]))
        part = CATALOG.get(str(child.get("part", "")))
        if parent.get(n) != me or child["source"] != "bought" or part is None or part["kind"] not in MOUNTED:
            continue
        cx, cy, cz = (centre[n][k] - centre[me][k] for k in range(3))
        sx, sy, sz = size[n]
        if cz - sz / 2 >= z1 - TOUCH:
            face, axis_dir, z = "top", "-", z1
        elif cz + sz / 2 <= z0 + TOUCH:
            face, axis_dir, z = "bottom", "+", z0
        else:
            continue
        for dx, dy in _pattern(part["kind"], [sx, sy]):
            x, y = cx + dx, cy + dy
            if not (x0 + 1.5 <= x <= x1 - 1.5 and y0 + 1.5 <= y <= y1 - 1.5) or (round(x), round(y), face) in seen:
                continue
            seen.add((round(x), round(y), face))
            hole: dict[str, Any] = {"f": "hole", "kind": "plain", "at": [round(x, 2), round(y, 2), round(z, 2)], "axis": "z", "dir": axis_dir, "d": HOLE_D}
            if z1 - z0 > DEPTH + 1.5:
                hole["depth"] = DEPTH
            out.append(hole)
    return out[:MAX_FEATURES]
