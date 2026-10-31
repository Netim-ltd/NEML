# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Refit the SPEC 14.2 factors the spec does not give, from judged history (ADR-014).

expected_gain   how often a task of this kind is judged done
cheapness       how short its runs are next to the other kinds

Both are shrunk toward the prior with PSEUDO pseudo-observations, so three lucky
runs cannot swing the queue and an empty history changes nothing.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .discovery import PRIOR_CHEAP, PRIOR_GAIN, Factors

PSEUDO = 5  # weight of the prior, in runs
FLOOR, CEIL = 0.05, 1.0


@dataclass(slots=True, frozen=True)
class RunRecord:
    kind: str
    done: bool  # the judge's verdict, not the executor's claim
    duration_s: float


def _shrink(observed: float, n: int, prior: float) -> float:
    return (observed * n + prior * PSEUDO) / (n + PSEUDO)


def _clamp(x: float) -> float:
    return max(FLOOR, min(CEIL, x))


def fit(history: Sequence[RunRecord], previous: Factors | None = None) -> Factors:
    base = previous or Factors()
    by_kind: dict[str, list[RunRecord]] = defaultdict(list)
    for r in history:
        by_kind[r.kind].append(r)

    medians = {k: statistics.median(r.duration_s for r in rs) for k, rs in by_kind.items()}
    slowest = max(medians.values(), default=0.0)

    gain: dict[str, float] = dict(base.gain)
    cheap: dict[str, float] = dict(base.cheap)
    for kind, rs in by_kind.items():
        n = len(rs)
        rate = sum(r.done for r in rs) / n
        if kind in PRIOR_GAIN:  # repair and human priority do not use expected_gain
            gain[kind] = _clamp(_shrink(rate, n, PRIOR_GAIN[kind]))
        if kind in PRIOR_CHEAP and slowest > 0:
            cheap[kind] = _clamp(_shrink(1.0 - medians[kind] / slowest, n, PRIOR_CHEAP[kind]))
    return Factors(gain=gain, cheap=cheap)


def as_rows(factors: Factors, samples: Mapping[str, int]) -> list[dict[str, float | int | str]]:
    kinds = sorted(set(factors.gain) | set(factors.cheap))
    return [
        {
            "kind": k,
            "expected_gain": factors.g(k),
            "cheapness": factors.c(k),
            "samples": samples.get(k, 0),
        }
        for k in kinds
    ]
