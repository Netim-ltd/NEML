# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The lab's own forecast of what the simulator will say about a robot, learned from the lab's own runs.

Every simulated run of a generated robot is logged with the numbers that describe it (wheel track, wheelbase, wheel radius,
mass, height of the centre of mass) and what happened (tipped over, how far it drove). `warn(plan)` finds the logged robots
most like a new plan and, when most of them tipped, tells the planner before any part is built or any minute of Gazebo is spent.

# ponytail: k nearest neighbours on standardised numbers (no training step, no dependency); it says nothing until MIN_RUNS runs
exist, and it only knows the worlds that were run. Swap in a fitted model when the log is large."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

FEATURES = ("track_mm", "base_mm", "wheel_radius_mm", "mass_kg", "com_mm")
MIN_RUNS = 12  # fewer logged runs than this: no opinion
K = 5
WARN_AT = 0.6  # share of the nearest runs that tipped


def _vec(facts: dict[str, Any]) -> list[float]:
    return [float(facts.get(f, 0.0)) for f in FEATURES]


class WorldModel:
    def __init__(self, root: Path | None = None) -> None:
        if root is None:
            from neml_brain.learning.store import default_dir

            root = default_dir()
        self._path = root / "worldmodel.jsonl"

    def rows(self) -> list[dict[str, Any]]:
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    def log(self, facts: dict[str, Any], world: str, x_m: float, tipped: bool) -> None:
        """One finished run of a generated robot."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"f": _vec(facts), "world": world, "x_m": round(x_m, 3), "tipped": bool(tipped)}) + "\n")

    def predict(self, facts: dict[str, Any]) -> dict[str, Any] | None:
        """{p_tip, x_m, n, near} from the K most similar logged robots, or None while there is too little data."""
        rows = self.rows()
        if len(rows) < MIN_RUNS:
            return None
        q = _vec(facts)
        cols = list(zip(*(r["f"] for r in rows), strict=True))
        scale = [(max(c) - min(c)) or 1.0 for c in cols]
        near = sorted(rows, key=lambda r: math.dist([a / s for a, s in zip(q, scale, strict=True)], [a / s for a, s in zip(r["f"], scale, strict=True)]))[:K]
        return {
            "p_tip": sum(r["tipped"] for r in near) / len(near),
            "x_m": sum(r["x_m"] for r in near) / len(near),
            "n": len(rows),
            "near": near,
        }

    def warn(self, plan: dict[str, Any]) -> list[str]:
        """Findings for the planner's critique loop; empty when the plan is not wheeled-drivable or the model has no opinion."""
        from neml_brain.evolution.robot_sdf import NotDrivable, sdf_of

        try:
            _, facts = sdf_of(plan)
        except NotDrivable:
            return []  # the hard judges already say why
        guess = self.predict(facts)
        if guess is None or guess["p_tip"] < WARN_AT:
            return []
        return [
            f"dünya modeli: buna en çok benzeyen {K} koşunun {round(guess['p_tip'] * K)}'i devrildi (iz {facts['track_mm']} mm, dingil mesafesi {facts['base_mm']} mm, "
            f"ağırlık merkezi {facts['com_mm']} mm); izi genişlet ya da ağır parçaları alçalt"
        ]
