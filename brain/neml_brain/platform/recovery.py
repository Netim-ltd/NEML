# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pair a failed robot skill with a later successful recovery for the same task."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

MAX_RECOVERY_DELAY = timedelta(minutes=10)
TRAINABLE_FAILURES = frozenset(
    {
        "obstacle",
        "navigation_timeout",
        "alignment_error",
        "inspection_incomplete",
    }
)
IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


@dataclass(frozen=True)
class SkillOutcome:
    task_id: str
    operation: str
    action: str
    success: bool
    failure_class: str
    features: tuple[float, ...]
    quality: float
    occurred_at: datetime

    def __post_init__(self) -> None:
        if not self.task_id or len(self.task_id) > 128:
            raise ValueError("task ID missing or too long")
        if not IDENTIFIER.fullmatch(self.operation):
            raise ValueError("invalid operation")
        if not self.action or len(self.action) > 128:
            raise ValueError("invalid action")
        if type(self.success) is not bool:
            raise ValueError("success must be boolean")
        if any(isinstance(value, bool) for value in self.features):
            raise ValueError("features must be numeric")
        if not 1 <= len(self.features) <= 64 or any(
            not math.isfinite(value) or abs(value) > 1 for value in self.features
        ):
            raise ValueError("features must be normalized")
        if not math.isfinite(self.quality) or not 0 <= self.quality <= 1:
            raise ValueError("invalid quality")
        if self.occurred_at.tzinfo is None:
            raise ValueError("outcome timestamp needs a timezone")
        if not self.success and (not self.failure_class or len(self.failure_class) > 128):
            raise ValueError("failed skill needs a failure class")


class RecoveryTracker:
    def __init__(self) -> None:
        self.failures: dict[str, SkillOutcome] = {}

    def observe(
        self, outcome: SkillOutcome, *, now: datetime | None = None
    ) -> dict[str, object] | None:
        clock = now or datetime.now(UTC)
        if outcome.occurred_at > clock + timedelta(seconds=30):
            raise ValueError("outcome timestamp is in the future")
        self.failures = {
            task: failure
            for task, failure in self.failures.items()
            if timedelta(0) <= clock - failure.occurred_at <= MAX_RECOVERY_DELAY
        }
        if not outcome.success:
            if outcome.failure_class in TRAINABLE_FAILURES:
                self.failures[outcome.task_id] = outcome
            return None
        failed = self.failures.pop(outcome.task_id, None)
        if failed is None:
            return None
        if (
            failed.operation != outcome.operation
            or failed.action == outcome.action
            or not timedelta(0) < outcome.occurred_at - failed.occurred_at <= MAX_RECOVERY_DELAY
            or outcome.quality < 0.95
        ):
            return None
        return {
            "operation": outcome.operation,
            "features": list(failed.features),
            "failed_action": failed.action,
            "failure_class": failed.failure_class,
            "recovery_action": outcome.action,
            "outcome": "success",
            "quality": outcome.quality,
        }
