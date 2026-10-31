# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy. All rights reserved.
# Proprietary and confidential. Unauthorized use is prohibited.
"""Design for manufacture: plain checks on a built part's measurements and its recipe, per process. Findings are advice with numbers;
nothing here changes a design. # ponytail: heuristics on the thinnest wall, overhang area and drilled holes, not a full feature recognition."""

from __future__ import annotations

from typing import Any

PROCESSES = ("print", "cnc")
BED_MM = 220.0  # a common FDM bed
HOLE_RATIO_MAX = 4.0  # drilled depth / diameter for CNC


def review(process: str, info: dict[str, Any], recipe: dict[str, Any]) -> list[dict[str, str]]:
    if process not in PROCESSES:
        raise ValueError("process must be print or cnc")
    out: list[dict[str, str]] = []

    def add(severity: str, text: str) -> None:
        out.append({"severity": severity, "text": text})

    wall = info.get("min_wall_mm")
    bb = info.get("bbox") or [0] * 6
    size = [bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]]
    holes = [f for f in recipe.get("features") or [] if f.get("f") == "hole"]
    boxes = {s["id"] for s in recipe.get("solids") or [] if s.get("t") == "box"}
    pockets = [s for s in recipe.get("steps") or [] if s.get("op") == "cut" and s.get("b") in boxes]
    if process == "print":
        if wall is not None and wall < 1.2:
            add("high", f"en ince duvar {wall:g} mm: 0.4 mm nozulla en az 1.2 mm (3 çevre) gerekir")
        if max(size) > BED_MM:
            add("high", f"parça {max(size):.0f} mm: yazıcı tablasına ({BED_MM:.0f} mm) sığmaz, parçalara böl")
        area = info.get("area_mm2") or 0
        if area and info.get("overhang_mm2", 0) / area > 0.15:
            add("medium", f"yüzeyin %{100 * info['overhang_mm2'] / area:.0f}'i havada kalıyor (45° üstü); parçayı çevir ya da destek kullan")
        for h in holes:
            if h["d"] < 2:
                add("medium", f"Ø{h['d']:g} delik baskıda kapanır; delmek için sonradan matkap kullan")
            if h.get("kind") == "tap":
                add("low", f"M{h['d']:g} dişi plastikte çabuk bozulur; ısıyla yerleşen dişli burç öner")
        if min(size) > 0 and max(size) / min(size) > 12:
            add("medium", f"parça çok ince-uzun ({max(size):.0f}×{min(size):.0f} mm): baskı sırasında eğilir")
    else:
        if wall is not None and wall < 0.8:
            add("high", f"en ince duvar {wall:g} mm: frezede titrer, en az 0.8 mm olsun")
        for h in holes:
            if h.get("depth") and h["depth"] / h["d"] > HOLE_RATIO_MAX:
                add("medium", f"Ø{h['d']:g} x {h['depth']:g} delik derin (derinlik/çap {h['depth'] / h['d']:.1f} > {HOLE_RATIO_MAX:g}): kademeli delme gerekir")
            if h.get("kind") == "tap" and not h.get("depth"):
                add("low", f"M{h['d']:g} dişi için derinlik yaz (kör delik) ya da geçme açık bırakıldığını belirt")
        if pockets and not recipe.get("round"):
            add("medium", "kutu keserek yapılan ceplerin iç köşeleri keskin; freze kalemi yuvarlak bırakır, en az r=1.5 mm köşe yarıçapı ver")
        if size and max(size) > 600:
            add("high", "parça 600 mm üstünde, tezgâh strokuna sığmayabilir")
    return out
