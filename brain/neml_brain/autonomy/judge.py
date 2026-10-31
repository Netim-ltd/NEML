# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Outcome judge: was the task actually done? (ADR-014)

The executor's own `outcome` is a claim. The judge re-checks it against
acceptance criteria and independent evidence, then picks the correction:

    accept    the task is done
    retry     not done, nothing unsafe happened, attempts remain: run again
              with a fresh seed and the failure tag as a hint
    repair    attempts are spent and a skill is behind it: open a repair task
    escalate  a safety violation, missing independent evidence, or nothing left
              to try: stop and tell the owner

It is deterministic on purpose. A 1.5B model must not decide that a robot
task succeeded; it only helps tag the failure afterwards (learning.py).
"""

from __future__ import annotations

import operator
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

MAX_ATTEMPTS = 3
Action = Literal["accept", "retry", "repair", "escalate"]

_OPS: dict[str, Callable[[float, float], bool]] = {
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
    "==": operator.eq,
}

# Criteria applied when the task spec carries none of its own. They encode the
# acceptance rules the spec already states (SPEC 11.2 determinism, 11.3 gap).
DEFAULT_CRITERIA: dict[str, list[dict[str, Any]]] = {
    "calibration": [{"metric": "reality_gap", "op": "<=", "value": 0.20}],
    "maintenance": [{"metric": "reality_gap", "op": "<=", "value": 0.15}],
    "determinism": [{"metric": "max_deviation", "op": "<=", "value": 0.02}],
}
PHYSICAL_ENVS = frozenset({"bench", "tethered", "free"})


@dataclass(slots=True, frozen=True)
class TaskFacts:
    task_id: str
    kind: str
    spec: Mapping[str, Any]
    attempts: int  # runs recorded so far, including the one being judged
    skill_key: str | None = None


@dataclass(slots=True, frozen=True)
class RunFacts:
    outcome: str  # what the executor claimed
    env: str
    metrics: Mapping[str, Any] = field(default_factory=dict)
    failure_tag: str | None = None


@dataclass(slots=True, frozen=True)
class Verdict:
    done: bool
    action: Action
    reasons: tuple[str, ...] = ()
    next_spec: Mapping[str, Any] | None = None  # for retry: the adjusted spec


def criteria_for(task: TaskFacts) -> list[dict[str, Any]]:
    explicit = task.spec.get("acceptance")
    if isinstance(explicit, list) and explicit:
        return [dict(c) for c in explicit]
    return list(DEFAULT_CRITERIA.get(str(task.spec.get("action", task.kind)), ()))


def _check(criterion: Mapping[str, Any], metrics: Mapping[str, Any]) -> str | None:
    """None when it holds, else the reason it does not."""
    metric, op, want = criterion.get("metric"), criterion.get("op"), criterion.get("value")
    if op not in _OPS or not isinstance(metric, str) or not isinstance(want, (int, float)):
        return f"malformed criterion {dict(criterion)}"
    got = metrics.get(metric)
    if isinstance(got, bool) or not isinstance(got, (int, float)):
        return f"{metric}: no measurement"  # a missing number is a failure, never a pass
    return None if _OPS[op](float(got), float(want)) else f"{metric} {got} not {op} {want}"


def judge(task: TaskFacts, run: RunFacts) -> Verdict:
    reasons: list[str] = []
    unsafe = bool(run.metrics.get("safety_violation"))
    if unsafe:
        reasons.append("safety violation reported")
    if run.outcome != "success":
        reasons.append(f"executor outcome: {run.outcome}")
    if run.env in PHYSICAL_ENVS and run.metrics.get("sensor_verified") is not True:
        reasons.append("no independent sensor verification")
    reasons += [r for c in criteria_for(task) if (r := _check(c, run.metrics))]

    if not reasons:
        return Verdict(True, "accept")

    needs_human = unsafe or any("sensor verification" in r for r in reasons)
    if needs_human:
        return Verdict(False, "escalate", tuple(reasons))
    if task.attempts < MAX_ATTEMPTS:
        return Verdict(False, "retry", tuple(reasons), _retry_spec(task, run))
    if task.skill_key:
        return Verdict(False, "repair", tuple(reasons))
    return Verdict(False, "escalate", tuple(reasons))


def _retry_spec(task: TaskFacts, run: RunFacts) -> dict[str, Any]:
    """Same task, next seed, and the failure tag so the planner can adapt."""
    spec = dict(task.spec)
    spec["seed"] = int(spec.get("seed", 0)) + 1
    spec["retry_of_attempt"] = task.attempts
    if run.failure_tag:
        spec["failure_hint"] = run.failure_tag
    return spec


def judge_many(pairs: Sequence[tuple[TaskFacts, RunFacts]]) -> list[Verdict]:
    return [judge(t, r) for t, r in pairs]
