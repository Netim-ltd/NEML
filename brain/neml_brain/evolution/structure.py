# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Static structural analysis of a genome's printed parts: the structure's own analyst.

Hand calculations, not a finite-element solve (FreeCAD FEM is not in the lab's images): a leg link
is a hollow rectangular cantilever carrying a share of the body weight at its tip with a dynamic
factor; the check gives stress, safety factor against a printed-part yield (halved for layer
anisotropy), tip deflection and the joint torque it asks of a servo. Joint details (hole edge
distance, wall thickness) are checked against printing rules. Findings are plain data the critic
and the learning loop read; nothing here changes a design.
"""

from __future__ import annotations

from typing import Any

G = 9.81
DYNAMIC = 2.5  # a trotting step lands on one or two legs with this multiple of the static load
# MPa: printed-part yield (along the layers) and Young's modulus
MATERIAL = {
    "PETG": (45.0, 2100.0),
    "PA6-CF": (70.0, 5000.0),
    "PLA": (50.0, 3500.0),
    "ASA": (38.0, 2000.0),
}
ANISOTROPY = 0.5
MIN_SAFETY = 2.0
MAX_DEFLECTION_RATIO = 0.03  # tip deflection / length


def generic_link(
    size_mm: list[float], volume_mm3: float, material: str, body_kg: float, mass_g: float
) -> list[dict[str, Any]]:
    """Estimate for any designed link from its built solid: a beam-like part (long against its section) is a cantilever with the same load model as a leg."""
    length, mid, small = sorted(size_mm, reverse=True)
    if small <= 0 or length < 3 * small:
        return []  # a block or plate: no beam estimate
    solidity = min(volume_mm3 / (length * mid * small), 1.0)
    inertia = mid * small**3 / 12 * solidity
    yield_mpa, _ = MATERIAL.get(material, MATERIAL["PETG"])
    force = body_kg * G / 2 * DYNAMIC
    stress = force * length * (small / 2) / inertia
    safety = yield_mpa * ANISOTROPY / stress
    if safety >= MIN_SAFETY:
        return []
    text = f"parça {length:.0f}×{mid:.0f}×{small:.0f} mm ({material}): kiriş tahmini emniyet katsayısı {safety:.1f} (≥{MIN_SAFETY} olmalı)"
    return [
        {
            "area": "structure",
            "severity": "high" if safety < 1 else "medium",
            "text": text,
            "metric": safety,
        }
    ]


def analyze(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Findings for the designed (CAD) parts of one genome body: each part's own solid, by the beam estimate."""
    mech = body["mechanical"]
    kg = float(mech.get("body_mass_kg", 1.0))
    findings: list[dict[str, Any]] = []
    for e in mech.get("imports", []):
        design = e.get("design")
        if e.get("kind") != "stl" or not design:
            continue
        for f in generic_link(
            list(e["size"]),
            float(design.get("volume_mm3", 0)),
            str(design.get("material")),
            kg,
            0.0,
        ):
            findings.append({**f, "text": f"{e['name']}: {f['text']}"})
    return findings
