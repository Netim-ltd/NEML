# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Designs are looked at again, not once: the active generated robots are re-judged with today's judges and score, and the weakest is
designed again with its own findings as the brief. Each model has a cooldown and a round limit, so the lab never loops on one robot.

# ponytail: the new design is a separate model when its name differs; whether it beats the old one shows in the world model's runs."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

COOLDOWN_H = 24.0
MAX_ROUNDS = 3  # revisits per model, ever
GOOD_ENOUGH = 4.0  # plan_score at or above this with no findings: leave it alone


def _book(root: Path) -> dict[str, Any]:
    try:
        return dict(json.loads((root / "revisits.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}


def review(plan: dict[str, Any]) -> tuple[float, list[str]]:
    """(plan score, findings) of a stored plan under the judges as they are now."""
    from neml_brain.evolution.generative import layout_issues, plan_score
    from neml_brain.evolution.judges import robot_issues

    return plan_score(plan)[0], [*robot_issues(plan), *layout_issues(plan)]


def pick(root: Path, designs: dict[str, dict[str, Any]], now: float | None = None) -> tuple[str, str] | None:
    """(model, brief) of the design most worth another round, or None. `designs` maps model -> its generated record (brief, plan)."""
    now = time.time() if now is None else now
    book = _book(root)
    ranked: list[tuple[float, str, str]] = []
    for model, gen in designs.items():
        seen = book.get(model, {"n": 0, "at": 0.0})
        if seen["n"] >= MAX_ROUNDS or now - seen["at"] < COOLDOWN_H * 3600:
            continue
        try:
            score, found = review(gen["plan"])
        except (KeyError, ValueError, TypeError):  # an old design the current judges cannot read: nothing to compare
            continue
        if not found and score >= GOOD_ENOUGH:
            continue
        brief = (
            f"{gen.get('brief', '')[:300]}\nBu isteğin önceki tasarımı '{gen['plan'].get('name', model)}' bugünkü yargıçlarla puanı {score:.1f}, "
            f"bulgular: {'; '.join(found[:5]) or 'bulgu yok ama puan düşük (engel aşma, zemin boşluğu, devrilme payı, ağırlık)'}. "
            "Aynı işi gören, bu eksikleri gideren daha iyi bir tasarım yaz."
        )
        ranked.append((score - 3.0 * len(found), model, brief))
    if not ranked:
        return None
    _, model, brief = min(ranked)
    return model, brief


def mark(root: Path, model: str, now: float | None = None) -> None:
    book = _book(root)
    book[model] = {"n": book.get(model, {"n": 0})["n"] + 1, "at": time.time() if now is None else now}
    (root / "revisits.json").write_text(json.dumps(book), encoding="utf-8")
