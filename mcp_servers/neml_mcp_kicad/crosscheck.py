# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A second reader for a drawn board: it does not ask KiCad, it reads the .kicad_pcb text itself.

Two questions KiCad's DRC answers in its own way are answered again here from the file alone:
does every pad sit on the net the circuit recipe gave it, and is every net's copper (tracks, vias,
through-hole pads) one connected piece? GND is carried by the back-side zone, so it is only checked for names.
A disagreement with the DRC verdict is itself worth a look.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

FOOTPRINT = re.compile(r'\(footprint "[^"]*"(.*?)\n  \)', re.S)
NUM = r"(-?\d+\.?\d*)"
SEGMENT = re.compile(rf'\(segment \(start {NUM} {NUM}\) \(end {NUM} {NUM}\) \(width {NUM}\) \(layer "([^"]+)"\) \(net (\d+)\)')
VIA = re.compile(rf"\(via \(at {NUM} {NUM}\) \(size {NUM}\).*?\(net (\d+)\)", re.S)
PAD = re.compile(rf'\(pad "([^"]+)" (smd|thru_hole|through_hole) \w+ \(at {NUM} {NUM}\) \(size {NUM} {NUM}\).*?\(net \d+ "([^"]*)"\)', re.S)




def _find(parent: dict[Any, Any], a: Any) -> Any:
    while parent.setdefault(a, a) != a:
        parent[a] = parent[parent[a]]
        a = parent[a]
    return a


def cross_check(circuit: dict[str, Any], board_text: str) -> dict[str, Any]:
    """Issues found by reading the board file against the circuit recipe (empty = the two readers agree)."""
    issues: list[str] = []
    wanted = {p["ref"]: {str(pin[0]): pin[3] for pin in p["pins"]} for p in circuit["parts"]}
    pads: dict[str, list[tuple[float, float, float, str, str]]] = defaultdict(list)  # net -> (x, y, reach, kind, ref)
    seen: set[str] = set()
    shapes: list[list[Any]] = []  # [x, y, w, h, net, "U1.2", "smd"|"tht"] for the drawing a screen makes of the board
    centres: dict[str, list[float]] = {}
    for fp in FOOTPRINT.finditer(board_text):
        body = fp.group(0)
        ref = re.search(r'\(property "Reference" "([^"]+)"', body)
        at = re.search(rf"\n    \(at {NUM} {NUM}\)", body)
        if not ref or not at:
            continue
        name, ox, oy = ref.group(1), float(at.group(1)), float(at.group(2))
        seen.add(name)
        centres[name] = [round(ox, 3), round(oy, 3)]
        for num, kind, px, py, w, h, net in ((m[0], m[1], float(m[2]), float(m[3]), float(m[4]), float(m[5]), m[6]) for m in PAD.findall(body)):
            if name in wanted and wanted[name].get(num) not in (None, net):
                issues.append(f"{name}.{num}: board has net {net}, circuit says {wanted[name][num]}")
            shapes.append([round(ox + px, 3), round(oy + py, 3), w, h, net, f"{name}.{num}", "smd" if kind == "smd" else "tht"])
            pads[net].append((ox + px, oy + py, max(w, h) / 2, "smd" if kind == "smd" else "tht", f"{name}.{num}"))
    for ref in sorted(set(wanted) - seen):
        issues.append(f"{ref} is in the circuit but not on the board")
    for ref in sorted(seen - set(wanted)):
        issues.append(f"{ref} is on the board but not in the circuit")
    names = {int(i): n for i, n in re.findall(r'\(net (\d+) "([^"]*)"\)\n', board_text)}
    copper: dict[str, list[tuple[Any, ...]]] = defaultdict(list)  # net -> ("seg", layer, x1, y1, x2, y2, half-width) | ("via", x, y, radius)
    for m in SEGMENT.finditer(board_text):
        x1, y1, x2, y2, w = (float(m.group(i)) for i in range(1, 6))
        copper[names.get(int(m.group(7)), "")].append(("seg", m.group(6), x1, y1, x2, y2, w / 2))
    for m in VIA.finditer(board_text):
        copper[names.get(int(m.group(4)), "")].append(("via", float(m.group(1)), float(m.group(2)), float(m.group(3)) / 2))
    for net, plist in pads.items():
        if net == "GND" or len(plist) < 2:
            continue
        items: list[tuple[Any, ...]] = [("pad", *p) for p in plist] + copper.get(net, [])
        parent: dict[int, int] = {}
        for i, a_ in enumerate(items):
            for j in range(i + 1, len(items)):
                if _touch(a_, items[j]):
                    parent[_find(parent, i)] = _find(parent, j)
        roots = {_find(parent, i) for i, it in enumerate(items) if it[0] == "pad"}
        if len(roots) > 1:
            issues.append(f"net {net}: copper falls into {len(roots)} separate pieces")
    geometry = {
        "parts": centres,
        "pads": shapes,
        "tracks": [[names.get(int(m.group(7)), ""), m.group(6), *(float(m.group(i)) for i in range(1, 6))] for m in SEGMENT.finditer(board_text)],
        "vias": [[names.get(int(m.group(4)), ""), float(m.group(1)), float(m.group(2)), float(m.group(3))] for m in VIA.finditer(board_text)],
    }
    return {"passed": not issues, "issues": issues[:12], "nets": len(pads), "pads": sum(len(v) for v in pads.values()), "geometry": geometry}


def _dist(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    dx, dy = x2 - x1, y2 - y1
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return float(((px - x1 - t * dx) ** 2 + (py - y1 - t * dy) ** 2) ** 0.5)


def _touch(a: tuple[Any, ...], b: tuple[Any, ...]) -> bool:
    """Do two pieces of copper of one net touch? Pads and vias are discs (a pad's longer half side), tracks have a width; the layer must agree."""
    def disc(it: tuple[Any, ...]) -> tuple[float, float, float, set[str]] | None:
        if it[0] == "pad":  # (x, y, reach, kind, ref)
            return it[1], it[2], it[3], {"F.Cu", "B.Cu"} if it[4] == "tht" else {"F.Cu"}
        if it[0] == "via":
            return it[1], it[2], it[3], {"F.Cu", "B.Cu"}
        return None

    da, db = disc(a), disc(b)
    if da and db:
        return bool(_dist(da[0], da[1], db[0], db[1], db[0], db[1]) <= da[2] + db[2] and da[3] & db[3])
    if da or db:
        d, seg = da or db, (b if da else a)
        return bool(d and seg[1] in d[3] and _dist(d[0], d[1], seg[2], seg[3], seg[4], seg[5]) <= d[2] + seg[6] + 0.01)
    if a[1] != b[1]:
        return False
    ends = ((a[2], a[3]), (a[4], a[5]))
    near = min(_dist(x, y, b[2], b[3], b[4], b[5]) for x, y in ends)
    near = min(near, *(_dist(x, y, a[2], a[3], a[4], a[5]) for x, y in ((b[2], b[3]), (b[4], b[5]))))
    return bool(near <= a[6] + b[6] + 0.01)
