# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where imported meshes go in the scene, so a repository of parts is understandable on screen.

Three cases, in this order:
  1. the repository ships a URDF/xacro: every visual (mesh, box, cylinder, sphere) is placed by the
     joint tree (`assembly` of the urdf entry), a mesh used four times appears four times, in
     millimetres; the scene also gets the joint tree (`rig`) so the viewer can pose the robot;
  2. no URDF, but the parts already sit in one assembly frame (their boxes hardly overlap): they
     stay where the files put them;
  3. no URDF and the parts pile up on top of each other (each is modelled in its own frame): they
     are laid out in a labelled grid on the ground, largest first, so each one can be seen.

When a repository has several URDFs, the one that explains the most imported parts is used.
A URDF mesh `foo.dae` is matched to an imported `foo.stl` (same name, other format).

Units: a URDF scale says what a mesh unit is. Without one, a model whose longest part is under
3 units is taken to be in metres (a 20 cm robot is 0.2), anything else in millimetres.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import Any

import numpy as np

GAP_MM = 30.0
STACKED_FRACTION = 0.25  # share of part pairs that overlap before the set counts as piled up
METRES_BELOW = 3.0
MESH_KINDS = ("stl", "step")


def unit_factor(entries: Sequence[Mapping[str, Any]]) -> float:
    """Mesh units -> millimetres when no URDF says: metres if everything is tiny."""
    longest = max((max(e["size"]) for e in entries), default=0.0)
    return 1000.0 if 0 < longest < METRES_BELOW else 1.0


def rotate(quat: Sequence[float], vector: Sequence[float] | np.ndarray) -> np.ndarray:
    x, y, z, w = quat
    r = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )
    return np.asarray(r @ np.asarray(vector, dtype=float))


def overlap_fraction(boxes: Sequence[tuple[np.ndarray, np.ndarray]]) -> float:
    """Share of part pairs whose boxes share more than 30% of the smaller one."""
    pairs = list(itertools.combinations(boxes, 2))
    if not pairs:
        return 0.0
    hits = 0
    for (alo, ahi), (blo, bhi) in pairs:
        inter = float(np.prod(np.clip(np.minimum(ahi, bhi) - np.maximum(alo, blo), 0, None)))
        small = min(float(np.prod(ahi - alo)), float(np.prod(bhi - blo)))
        hits += small > 0 and inter > 0.3 * small
    return hits / len(pairs)


def grid(
    entries: Sequence[Mapping[str, Any]], factor: float, origin_y: float = 0.0
) -> dict[str, list[float]]:
    """Positions of each entry's box centre in a ground grid, the largest part first."""
    sizes = {e["id"]: [float(v) * factor for v in e["size"]] for e in entries}
    order = sorted(sizes, key=lambda i: -(sizes[i][0] * sizes[i][1] * sizes[i][2]))
    area = sum((sizes[i][0] + GAP_MM) * (sizes[i][1] + GAP_MM) for i in order)
    row_width = max(math.sqrt(area) * 1.4, max((sizes[i][0] for i in order), default=0.0))
    pos: dict[str, list[float]] = {}
    x = y = row_depth = 0.0
    for ident in order:
        sx, sy, _ = sizes[ident]
        if x > 0 and x + sx > row_width:
            y += row_depth + GAP_MM
            x = row_depth = 0.0
        pos[ident] = [x + sx / 2, y + sy / 2, sizes[ident][2] / 2]
        x += sx + GAP_MM
        row_depth = max(row_depth, sy)
    if not pos:
        return pos
    shift_x = max(p[0] + sizes[i][0] / 2 for i, p in pos.items()) / 2
    shift_y = (y + row_depth) / 2
    return {i: [p[0] - shift_x, p[1] - shift_y + origin_y, p[2]] for i, p in pos.items()}


def stem(name: str) -> str:
    return PurePosixPath(name.lower()).stem


def mesh_index(
    meshes: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    by_file = {str(e.get("file") or f"{e['name']}.stl").lower(): e for e in meshes}
    by_stem = {stem(f): e for f, e in by_file.items()}
    return by_file, by_stem


def matched(urdf: Mapping[str, Any], meshes: Sequence[Mapping[str, Any]]) -> int:
    by_file, by_stem = mesh_index(meshes)
    count = 0
    for a in urdf.get("assembly") or []:
        if a.get("shape") or (
            a.get("mesh") and (a["mesh"] in by_file or stem(a["mesh"]) in by_stem)
        ):
            count += 1
    return count


def mass_count(urdf: Mapping[str, Any]) -> int:
    return len(((urdf.get("rig") or {}).get("links")) or {})


def movable_count(urdf: Mapping[str, Any]) -> int:
    return int((urdf.get("urdf") or {}).get("movable_joints", 0))


def chosen_urdf(imports: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """The URDF that explains the most of what was imported (None when there is none)."""
    meshes = [e for e in imports if e["kind"] in MESH_KINDS and e.get("urls", {}).get("stl")]
    urdfs = [e for e in imports if e["kind"] == "urdf" and e.get("assembly")]
    if not urdfs:
        return None
    best = max(
        urdfs, key=lambda u: (matched(u, meshes), movable_count(u), mass_count(u))
    )  # then the one that moves
    return best if matched(best, meshes) else None


def place(imports: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:  # noqa: C901 - three layout cases
    """One placement per visible part: pose, size, unit factor and, for a URDF, link and colour."""
    meshes = [e for e in imports if e["kind"] in MESH_KINDS and e.get("urls", {}).get("stl")]
    by_file, by_stem = mesh_index(meshes)
    out: list[dict[str, Any]] = []
    placed: set[str] = set()
    urdf = chosen_urdf(imports)
    urdf_id = str((urdf or {}).get("id", "urdf"))
    for i, a in enumerate((urdf or {}).get("assembly") or []):
        base = {
            "pos": [round(float(v), 2) for v in a["pos"]],
            "quat": list(a["quat"]),
            "link": a["link"],
            "color": a.get("color"),
        }
        if a.get("shape"):
            shape = a["shape"]
            size = (
                list(shape["size"])
                if shape["type"] == "box"
                else [2 * shape["radius"]] * 2 + [shape.get("length", 2 * shape["radius"])]
                if shape["type"] == "cylinder"
                else [2 * shape["radius"]] * 3
            )
            out.append(
                {
                    **base,
                    "entry": None,
                    "shape": shape,
                    "id": f"{urdf_id}_s{i}",
                    "label": f"{a['link']} ({shape['type']})",
                    "size": size,
                    "factor": 1.0,
                    "local_pos": list(a.get("vpos", [0, 0, 0])),
                    "local_quat": list(a.get("vquat", [0, 0, 0, 1])),
                }
            )
            continue
        entry = by_file.get(str(a["mesh"]).lower()) or by_stem.get(stem(str(a["mesh"])))
        if entry is None:
            continue
        f = float(a["factor"])
        f3 = np.asarray(a.get("scale3") or [f, f, f], dtype=float)
        centre = rotate(a["quat"], np.asarray(entry.get("center", [0, 0, 0]), dtype=float) * f3)
        local = np.asarray(a.get("vpos", [0, 0, 0]), dtype=float) + rotate(
            a.get("vquat", [0, 0, 0, 1]),
            np.asarray(entry.get("center", [0, 0, 0]), dtype=float) * f3,
        )
        out.append(
            {
                **base,
                "entry": entry,
                "shape": None,
                "id": f"{entry['id']}_p{i}",
                "label": f"{a['link']} · {entry['name']}",
                "pos": [round(float(v), 2) for v in np.asarray(a["pos"], dtype=float) + centre],
                "size": [float(v) * float(s) for v, s in zip(entry["size"], f3, strict=True)],
                "factor": f,
                "scale3": list(map(float, f3)) if a.get("scale3") else None,
                "local_pos": [round(float(v), 3) for v in local],
                "local_quat": list(a.get("vquat", [0, 0, 0, 1])),
            }
        )
        placed.add(entry["id"])
    rest = [e for e in meshes if e["id"] not in placed]
    if not rest:
        return out
    f = unit_factor(rest)
    boxes = [
        (
            np.asarray(e["center"], dtype=float) * f - np.asarray(e["size"], dtype=float) * f / 2,
            np.asarray(e["center"], dtype=float) * f + np.asarray(e["size"], dtype=float) * f / 2,
        )
        for e in rest
    ]
    plain = {"quat": None, "link": None, "color": None, "shape": None, "scale3": None}
    if out or (len(rest) > 2 and overlap_fraction(boxes) >= STACKED_FRACTION):
        beside = 0.0
        if out:  # keep the table clear of the assembled robot
            beside = max(p["pos"][1] + p["size"][1] / 2 for p in out) + 200.0
        spots = grid(rest, f, origin_y=beside)
        for e in rest:
            out.append(
                {
                    **plain,
                    "entry": e,
                    "id": e["id"],
                    "label": f"{e['name']} ({e['repo']})",
                    "pos": [round(v, 2) for v in spots[e["id"]]],
                    "factor": f,
                    "size": [float(v) * f for v in e["size"]],
                    "table": True,
                }
            )
        return out
    for e in rest:  # one assembly frame: keep the files' own coordinates
        out.append(
            {
                **plain,
                "entry": e,
                "id": e["id"],
                "label": f"{e['name']} ({e['repo']})",
                "pos": [round(float(v) * f, 2) for v in e["center"]],
                "factor": f,
                "size": [float(v) * f for v in e["size"]],
            }
        )
    return out


def rig_of_imports(imports: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """The joint tree of the URDF in use, if it has anything to move."""
    urdf = chosen_urdf(imports)
    rig = (urdf or {}).get("rig")
    if not rig or not rig.get("joints"):
        return None
    return {"name": (urdf or {}).get("name", ""), **rig}
