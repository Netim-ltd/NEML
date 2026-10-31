# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 11.2 determinism arithmetic for neml-mcp-sim (T-036).

Pure functions over metric dicts: no Gazebo, no I/O, and - SPEC 11.2 rule 4 - no
clock of any kind. The 2% rule and the rule-3 exclusion live here rather than in
`server`, so the part that decides whether a run may influence evolution is the
part that can be tested exhaustively on a host with no simulator installed.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

TOLERANCE = 0.02  # SPEC 11.2 rule 3 - metrics must match within 2%.
DEFAULT_RUNS = 10  # T-036 - ten runs from one seed.
_ZERO_FLOOR = 1e-9  # A zero baseline still needs a denominator.


@dataclass(frozen=True)
class DeterminismReport:
    """The T-036 verdict for one seed. `deterministic=False` is an exclusion."""

    seed: int
    sim_version: str
    runs: int
    deterministic: bool
    max_deviation: float
    worst_metric: str
    tolerance: float
    per_run: list[dict[str, float]] = field(default_factory=list)
    randomization: dict[str, Any] = field(default_factory=dict)


def deviations(baseline: Mapping[str, float], values: Mapping[str, float]) -> dict[str, float]:
    """Relative deviation per metric.

    A metric that appears on one side only is infinitely deviant: two runs that
    do not even report the same metrics are not comparable, and "not comparable"
    must fail the same way "wildly different" does.
    """
    out: dict[str, float] = {}
    for key in set(baseline) | set(values):
        if key not in baseline or key not in values:
            out[key] = math.inf
        else:
            out[key] = abs(values[key] - baseline[key]) / max(abs(baseline[key]), _ZERO_FLOOR)
    return out


def worst(devs: Mapping[str, float]) -> tuple[str, float]:
    """The metric that drifted most. No metrics at all is a failure, not a pass."""
    if not devs:
        return "", math.inf
    key = max(devs, key=lambda k: devs[k])
    return key, devs[key]


def within_tolerance(
    baseline: Mapping[str, float], values: Mapping[str, float], tolerance: float = TOLERANCE
) -> bool:
    """SPEC 11.2 rule 3, for a single repeat against its baseline."""
    return worst(deviations(baseline, values))[1] <= tolerance


def compare_runs(
    seed: int,
    sim_version: str,
    runs: Sequence[Mapping[str, float]],
    tolerance: float = TOLERANCE,
    randomization: Mapping[str, Any] | None = None,
) -> DeterminismReport:
    """T-036: N runs of one seed against the first run.

    Every repeat is compared to run 0, not to its predecessor, so a slow drift
    across ten runs cannot hide behind ten small step-to-step differences.
    """
    if len(runs) < 2:
        raise ValueError("a determinism verdict needs at least two runs")
    baseline = runs[0]
    per_run = [deviations(baseline, values) for values in runs[1:]]
    # An empty baseline is not a clean run, it is a run that measured nothing.
    worst_metric, max_deviation = "", (0.0 if baseline else math.inf)
    for devs in per_run:
        metric, value = worst(devs)
        if value > max_deviation:
            worst_metric, max_deviation = metric, value
    return DeterminismReport(
        seed=seed,
        sim_version=sim_version,
        runs=len(runs),
        deterministic=max_deviation <= tolerance,
        max_deviation=max_deviation,
        worst_metric=worst_metric,
        tolerance=tolerance,
        per_run=per_run,
        randomization=dict(randomization or {}),
    )


def usable_runs(runs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """SPEC 11.2 rule 3: a flagged run must not reach an evolution decision.

    Fails closed - a row with no `deterministic` field is dropped, because an
    unknown verdict is not a passing verdict.
    """
    return [dict(run) for run in runs if run.get("deterministic") is True]
