# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Robot outcome pairing must not turn an unverified error into a label."""

from datetime import UTC, datetime, timedelta

from neml_brain.platform.recovery import RecoveryTracker, SkillOutcome


def _outcome(
    now: datetime,
    *,
    success: bool,
    action: str,
    failure_class: str = "obstacle",
    quality: float = 0.99,
    task_id: str = "task-1",
) -> SkillOutcome:
    return SkillOutcome(
        task_id, "recovery", action, success, failure_class, (0.2, 0.8), quality, now
    )


def test_matching_verified_recovery_becomes_trace() -> None:
    start = datetime.now(UTC)
    tracker = RecoveryTracker()
    assert tracker.observe(_outcome(start, success=False, action="forward"), now=start) is None
    trace = tracker.observe(
        _outcome(start + timedelta(seconds=20), success=True, action="stop"),
        now=start + timedelta(seconds=20),
    )
    assert trace == {
        "operation": "recovery",
        "features": [0.2, 0.8],
        "failed_action": "forward",
        "failure_class": "obstacle",
        "recovery_action": "stop",
        "outcome": "success",
        "quality": 0.99,
    }


def test_critical_failure_never_becomes_training_trace() -> None:
    start = datetime.now(UTC)
    tracker = RecoveryTracker()
    tracker.observe(
        _outcome(start, success=False, action="forward", failure_class="collision"), now=start
    )
    assert (
        tracker.observe(
            _outcome(start + timedelta(seconds=5), success=True, action="stop"),
            now=start + timedelta(seconds=5),
        )
        is None
    )


def test_stale_or_low_quality_recovery_is_rejected() -> None:
    start = datetime.now(UTC)
    tracker = RecoveryTracker()
    tracker.observe(_outcome(start, success=False, action="forward"), now=start)
    assert (
        tracker.observe(
            _outcome(start + timedelta(minutes=11), success=True, action="stop"),
            now=start + timedelta(minutes=11),
        )
        is None
    )
    tracker.observe(_outcome(start, success=False, action="forward"), now=start)
    assert (
        tracker.observe(
            _outcome(start + timedelta(seconds=1), success=True, action="stop", quality=0.5),
            now=start + timedelta(seconds=1),
        )
        is None
    )
