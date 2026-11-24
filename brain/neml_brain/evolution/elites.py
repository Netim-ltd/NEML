# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The best passed plan per kind of robot (joints x weight x size), so new variants can start from a different niche than the last winner.

# ponytail: MAP-Elites with three coarse axes in one JSON file; no mutation operator, the model reads the elite as a hint."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def niche(plan: dict[str, Any]) -> str:
    joints = sum(1 for lk in plan["links"] if lk["joint"]["type"] == "revolute")
    kg = sum(float(lk["mass_g"]) for lk in plan["links"]) / 1000
    side = max(max(float(v) for v in lk["dims_mm"]) for lk in plan["links"])
    return f"{min(joints, 6)}j-{'hafif' if kg < 0.6 else 'orta' if kg < 1.5 else 'agir'}-{'kucuk' if side < 200 else 'buyuk'}"


def _book(root: Path) -> dict[str, Any]:
    try:
        return dict(json.loads((root / "elites.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}


def keep(root: Path, plan: dict[str, Any], score: float) -> bool:
    """True when this plan is the new best of its niche."""
    book, key = _book(root), niche(plan)
    if key in book and book[key]["score"] >= score:
        return False
    book[key] = {"score": round(score, 2), "plan": plan}
    (root / "elites.json").write_text(json.dumps(book, ensure_ascii=False), encoding="utf-8")
    return True


def hint(root: Path, plan: dict[str, Any] | None, i: int) -> str:
    """Prompt text pointing at the i-th best elite whose niche differs from `plan`'s; empty when there is none."""
    book = _book(root)
    others = sorted((k for k in book if plan is None or k != niche(plan)), key=lambda k: -book[k]["score"])
    if not others:
        return ""
    k = others[i % len(others)]
    e = book[k]["plan"]
    parts = ", ".join(str(lk.get("part") or lk["name"]) for lk in e["links"][:12])
    return f"{chr(10)}Bu lab'da daha önce geçen farklı bir tasarım türü ({k}): '{e['name']}' ({parts}). Ondan esinlenip bu isteğe uyarla."
