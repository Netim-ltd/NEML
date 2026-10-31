# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 12.5 quality control: the form, the verdict and the systematic-deviation rule.

Pure logic plus two small files. The IO that needs the database, the genome or
the printer lives in server.py; everything here is a measurement in and a number
out, which is what makes the "third consecutive part" rule testable.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# SPEC 12.5 thresholds.
CRITICAL_DIMENSIONS = 3
DIMENSION_TOLERANCE_MM = 0.3
MASS_TOLERANCE_RATIO = 0.05
WARP_MAX_MM = 0.5

# SPEC 12.5: "three consecutive parts in the same direction" is systematic.
STREAK = 3
COMPENSATION_KEY = "xy_size_compensation"
# A runaway compensation would quietly destroy every part. Half a millimetre of
# total correction is already far past a healthy printer.
MAX_COMPENSATION_MM = 0.5

HISTORY_NAME = "qc_history.jsonl"


class QcError(RuntimeError):
    """The form does not carry the SPEC 12.5 measurement set."""


@dataclass
class QcForm:
    """The SPEC 12.5 form, exactly the five checks the mobile screen collects."""

    dim_nominal_mm: list[float] = field(default_factory=list)  # CAD, 3 critical dimensions
    dim_measured_mm: list[float] = field(default_factory=list)  # caliper
    hole_gauge_pass: bool = False  # pin gauge, pass/fail
    mass_cad_g: float = 0.0
    mass_measured_g: float = 0.0  # scale
    layer_adhesion_pass: bool = False  # visual + bend by hand
    warp_mm: float = 0.0  # flat surface + light


@dataclass
class QcVerdict:
    passed: bool
    failures: list[str]
    deviation_mm: float  # mean signed deviation of the three critical dimensions
    direction: int  # -1 undersized, +1 oversized, 0 dead on


def evaluate(form: QcForm) -> QcVerdict:
    """Apply the five SPEC 12.5 thresholds. Deviation is signed: it drives §12.5's
    systematic-deviation rule, which needs a direction and not an absolute value."""
    nominal, measured = list(form.dim_nominal_mm), list(form.dim_measured_mm)
    if len(nominal) != CRITICAL_DIMENSIONS or len(measured) != CRITICAL_DIMENSIONS:
        raise QcError(f"SPEC 12.5 needs exactly {CRITICAL_DIMENSIONS} caliper dimensions")
    if form.mass_cad_g <= 0:
        raise QcError("mass_cad_g must be positive: the mass check is relative to CAD")

    deltas = [m - n for n, m in zip(nominal, measured, strict=True)]
    failures = [
        f"dimension {i + 1}: {d:+.2f} mm > +/-{DIMENSION_TOLERANCE_MM} mm"
        for i, d in enumerate(deltas)
        if abs(d) > DIMENSION_TOLERANCE_MM
    ]
    if not form.hole_gauge_pass:
        failures.append("hole gauge: fail")
    mass_error = (form.mass_measured_g - form.mass_cad_g) / form.mass_cad_g
    if abs(mass_error) > MASS_TOLERANCE_RATIO:
        failures.append(f"mass: {mass_error:+.1%} > +/-{MASS_TOLERANCE_RATIO:.0%} of CAD")
    if not form.layer_adhesion_pass:
        failures.append("layer adhesion: fail")
    if form.warp_mm > WARP_MAX_MM:
        failures.append(f"warp: {form.warp_mm} mm > {WARP_MAX_MM} mm")

    deviation = sum(deltas) / len(deltas)
    return QcVerdict(
        passed=not failures,
        failures=failures,
        deviation_mm=round(deviation, 4),
        direction=(deviation > 0) - (deviation < 0),
    )


# --- SPEC 12.5 systematic deviation ----------------------------------------


def _history_file(jobs_dir: Path) -> Path:
    return jobs_dir / HISTORY_NAME


def _append(jobs_dir: Path, entry: dict[str, Any]) -> None:
    file = _history_file(jobs_dir)
    file.parent.mkdir(parents=True, exist_ok=True)
    entry["ts"] = datetime.now(UTC).isoformat()
    with file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def append_history(jobs_dir: Path, profile_id: str, print_job_id: str, verdict: QcVerdict) -> None:
    """One line per measured part. Append-only: the rule reads history, never rewrites it."""
    _append(
        jobs_dir,
        {
            "profile_id": profile_id,
            "print_job_id": print_job_id,
            "deviation_mm": verdict.deviation_mm,
            "direction": verdict.direction,
            "compensated": False,
        },
    )


def mark_compensated(jobs_dir: Path, profile_id: str, applied_mm: float) -> None:
    """A marker line, not a part: it closes the run that triggered the correction."""
    _append(
        jobs_dir,
        {
            "profile_id": profile_id,
            "print_job_id": None,
            "deviation_mm": 0.0,
            "direction": 0,
            "compensated": True,
            "applied_mm": applied_mm,
        },
    )


def _entries(jobs_dir: Path, profile_id: str) -> list[dict[str, Any]]:
    """This profile's parts since the last compensation, one entry per part.

    Two rules, both from SPEC 12.5's wording "three consecutive PARTS":
      * a part measured before a correction says nothing about the printer after
        it, so a compensation marker clears the run;
      * a re-measured part is the same part, so its latest form replaces its
        earlier one. Without that, submitting one form three times - a double tap
        on the mobile screen, a corrected reading - would move the slicer
        compensation off a single part.

    ponytail: full file scan per submission. Ceiling is roughly a year of prints on
    one machine; move the history to print_jobs.qc queries if it ever bites.
    """
    file = _history_file(jobs_dir)
    if not file.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if entry.get("profile_id") != profile_id:
            continue
        out = [e for e in out if e.get("print_job_id") != entry.get("print_job_id")]
        out.append(entry)
        if entry.get("compensated"):
            out = []
    return out


def systematic_deviation(jobs_dir: Path, profile_id: str) -> float | None:
    """The mean deviation to correct, or None when the run is not systematic yet.

    SPEC 12.5: three consecutive parts off in the same direction. Two are not a
    trend, and a part that measured dead on breaks the run.
    """
    recent = _entries(jobs_dir, profile_id)[-STREAK:]
    if len(recent) < STREAK:
        return None
    directions = {int(e["direction"]) for e in recent}
    if directions in ({1}, {-1}):
        return sum(float(e["deviation_mm"]) for e in recent) / STREAK
    return None


def apply_compensation(profile_path: Path, deviation_mm: float) -> tuple[float, float]:
    """Move the profile's XY size compensation to cancel a systematic deviation.

    PrusaSlicer grows/shrinks every contour by this value, so an outer dimension
    moves by twice it: half the measured deviation, with the sign flipped.
    Returns (old, new).
    """
    if not profile_path.is_file():
        raise QcError(f"slicer profile not found: {profile_path}")
    text = profile_path.read_text(encoding="utf-8")
    pattern = re.compile(rf"^({COMPENSATION_KEY}\s*=\s*)(-?[\d.]+)\s*$", re.MULTILINE)
    match = pattern.search(text)
    if match is None:
        raise QcError(f"{profile_path.name} has no {COMPENSATION_KEY} to update")
    old = float(match.group(2))
    new = round(old - deviation_mm / 2.0, 3)
    new = max(-MAX_COMPENSATION_MM, min(MAX_COMPENSATION_MM, new))
    profile_path.write_text(pattern.sub(rf"\g<1>{new}", text, count=1), encoding="utf-8")
    return old, new
