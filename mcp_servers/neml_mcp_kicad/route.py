# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A small deterministic autorouter for two-layer boards (grid A*, vias, clearance).

It routes net after net on a 0.25 mm grid: every pad and every finished track marks its
clearance zone as belonging to its net, a track may only pass through cells that are free or
belong to its own net, and a via is a step to the other layer through a cell that is free on both.
What cannot be routed is returned as `unrouted` so the routing agent can move parts and try again;
KiCad's own DRC is the judge of the result, not this module.
"""

from __future__ import annotations

import heapq
import math
import re
from typing import Any

from .emit import _pads

GRID = 0.25
CLEARANCE = 0.2
VIA_SIZE = 0.8
VIA_DRILL = 0.4
VIA_COST = 6
POWER_NET = re.compile(r"^(\+?\d+(\.\d+)?V\d*|V?CC|VIN|VBAT|BAT.*|VDD|VBUS|\+?5V|\+?3V3|\+?12V)$", re.IGNORECASE)
FRONT, BACK = 0, 1
LAYER = ("F.Cu", "B.Cu")


def width_of(net: str, track_mm: float) -> float:
    """Power nets get twice the signal width (never under 0.5 mm)."""
    return max(0.5, 2 * track_mm) if POWER_NET.match(net) else track_mm


def _segment(tracks: list[Any], net: str, a: tuple[int, int, int], b: tuple[int, int, int], w: float) -> float:
    p1, p2 = (a[1] * GRID, a[2] * GRID), (b[1] * GRID, b[2] * GRID)
    tracks.append((net, LAYER[b[0]], p1, p2, w))
    return abs(p2[0] - p1[0]) + abs(p2[1] - p1[1])


def autoroute(parts: list[dict[str, Any]], places: dict[str, tuple[float, float]], size: tuple[float, float], track_mm: float = 0.25) -> dict[str, Any]:
    """Tracks and vias for every net of the board.

    Returns {"tracks": [(net, layer, (x1, y1), (x2, y2), width)], "vias": [(net, (x, y), size, drill)],
    "unrouted": [net], "routed": [net], "length_mm": float}.
    """
    nx, ny = int(size[0] / GRID) + 1, int(size[1] / GRID) + 1
    max_w = max(0.5, 2 * track_mm)
    owner: list[dict[tuple[int, int], str]] = [{}, {}]

    def mark(layer: int, ix: int, iy: int, net: str) -> None:
        cell = (ix, iy)
        cur = owner[layer].get(cell)
        if cur is None:
            owner[layer][cell] = net
        elif cur != net:
            owner[layer][cell] = "*"

    def mark_disc(layer: int, ix: int, iy: int, net: str, radius: int) -> None:
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if dx * dx + dy * dy <= radius * radius:
                    mark(layer, ix + dx, iy + dy, net)

    # ---- pads: their rectangle plus clearance belongs to their net
    pads: dict[str, list[dict[str, Any]]] = {}
    for p in parts:
        if p["kind"] == "FLG" or p["ref"] not in places:
            continue
        cx, cy = places[p["ref"]]
        nets = dict(zip((n for n, *_r in p["pins"]), p["nets"], strict=True))
        for num, px, py, style, (pw, ph), _drill in _pads(p):
            net = nets[num]
            ax, ay = cx + px, cy + py
            layers = (FRONT,) if style == "smd" else (FRONT, BACK)
            grow = CLEARANCE + max_w / 2
            x0, x1 = int((ax - pw / 2 - grow) / GRID), int((ax + pw / 2 + grow) / GRID) + 1
            y0, y1 = int((ay - ph / 2 - grow) / GRID), int((ay + ph / 2 + grow) / GRID) + 1
            for layer in layers:
                for ix in range(x0, x1 + 1):
                    for iy in range(y0, y1 + 1):
                        mark(layer, ix, iy, net)
            cells = set()
            inner = 0.1  # a track must end well inside the copper (a circle for through-hole pads)
            for layer in layers:
                for ix in range(int((ax - pw / 2) / GRID), int((ax + pw / 2) / GRID) + 2):
                    for iy in range(int((ay - ph / 2) / GRID), int((ay + ph / 2) / GRID) + 2):
                        dx, dy = ix * GRID - ax, iy * GRID - ay
                        inside = dx * dx + dy * dy <= (pw / 2 - inner) ** 2 if style != "smd" else abs(dx) <= pw / 2 - inner and abs(dy) <= ph / 2 - inner
                        if inside:
                            cells.add((layer, ix, iy))
            if not cells:  # a pad smaller than the grid: its nearest cell
                cells = {(layer, round(ax / GRID), round(ay / GRID)) for layer in layers}
            pads.setdefault(net, []).append({"x": ax, "y": ay, "layers": layers, "cells": cells, "ref": p["ref"], "num": num})

    def passable(layer: int, ix: int, iy: int, net: str) -> bool:
        if not (0 <= ix < nx and 0 <= iy < ny):
            return False
        return owner[layer].get((ix, iy)) in (None, net)

    def via_ok(ix: int, iy: int, net: str) -> bool:
        """A via is wider than a track: its neighbours on both layers must be free too."""
        return all(passable(layer, ix + dx, iy + dy, net) for layer in (FRONT, BACK) for dx in (-1, 0, 1) for dy in (-1, 0, 1))

    def search(net: str, sources: set[tuple[int, int, int]], targets: set[tuple[int, int, int]]) -> list[tuple[int, int, int]] | None:
        goal = next(iter(targets))
        gx, gy = goal[1], goal[2]
        heap: list[tuple[float, float, tuple[int, int, int]]] = []
        best: dict[tuple[int, int, int], float] = {}
        came: dict[tuple[int, int, int], tuple[int, int, int] | None] = {}
        for s in sources:
            best[s] = 0.0
            came[s] = None
            heapq.heappush(heap, (abs(s[1] - gx) + abs(s[2] - gy), 0.0, s))
        while heap:
            _f, g, cur = heapq.heappop(heap)
            if g > best.get(cur, math.inf):
                continue
            if cur in targets:
                path = [cur]
                while came[path[-1]] is not None:
                    path.append(came[path[-1]])  # type: ignore[arg-type]
                return path[::-1]
            layer, ix, iy = cur
            steps = [(layer, ix + 1, iy, 1.0), (layer, ix - 1, iy, 1.0), (layer, ix, iy + 1, 1.0), (layer, ix, iy - 1, 1.0)]
            if via_ok(ix, iy, net):
                steps.append((1 - layer, ix, iy, float(VIA_COST)))
            for nl, nx_, ny_, cost in steps:
                if nl == layer and not passable(nl, nx_, ny_, net):
                    continue
                state = (nl, nx_, ny_)
                ng = g + cost
                if ng < best.get(state, math.inf):
                    best[state] = ng
                    came[state] = cur
                    heapq.heappush(heap, (ng + abs(nx_ - gx) + abs(ny_ - gy), ng, state))
        return None

    tracks: list[tuple[str, str, tuple[float, float], tuple[float, float], float]] = []
    vias: list[tuple[str, tuple[float, float], float, float]] = []
    routed: list[str] = []
    unrouted: list[str] = []
    length = 0.0

    def span(net: str) -> float:
        pts = pads[net]
        return (max(p["x"] for p in pts) - min(p["x"] for p in pts)) + (max(p["y"] for p in pts) - min(p["y"] for p in pts))

    for net in sorted((n for n in pads if n and len(pads[n]) > 1), key=span):
        w = width_of(net, track_mm)
        radius = math.ceil((w / 2 + CLEARANCE + max_w / 2) / GRID)
        pts = pads[net]
        tree = {c for c in pts[0]["cells"]}
        ok = True
        paths: list[list[tuple[int, int, int]]] = []
        for pad in pts[1:]:
            path = search(net, tree, set(pad["cells"]))
            if path is None:
                ok = False
                break
            paths.append(path)
            tree |= set(path) | set(pad["cells"])
            for layer, ix, iy in path:
                mark_disc(layer, ix, iy, net, radius)
            via_radius = math.ceil((VIA_SIZE / 2 + CLEARANCE + max_w / 2) / GRID)
            for a_, b_ in zip(path, path[1:], strict=False):
                if a_[0] != b_[0]:  # the copper of a via is on both layers
                    for layer in (FRONT, BACK):
                        mark_disc(layer, b_[1], b_[2], net, via_radius)
        if not ok:
            unrouted.append(net)
            continue
        routed.append(net)
        for path in paths:
            start = path[0]
            for i in range(1, len(path)):
                a, b = path[i - 1], path[i]
                if b[0] != a[0]:  # the layer changes here: close the run and drop a via
                    if start != a:
                        length += _segment(tracks, net, start, a, w)
                    vias.append((net, (b[1] * GRID, b[2] * GRID), VIA_SIZE, VIA_DRILL))
                    start = b
                    continue
                nxt = path[i + 1] if i + 1 < len(path) else None
                straight = nxt is not None and nxt[0] == b[0] and (b[1] - a[1], b[2] - a[2]) == (nxt[1] - b[1], nxt[2] - b[2])
                if not straight:
                    if start != b and start[0] == b[0]:
                        length += _segment(tracks, net, start, b, w)
                    start = b
    return {"tracks": tracks, "vias": vias, "unrouted": unrouted, "routed": routed, "length_mm": round(length, 1)}
