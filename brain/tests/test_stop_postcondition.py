# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The independent stop verifier needs a continuous measured window."""

from datetime import UTC, datetime, timedelta

from neml_brain.platform.postcondition import MotionSample, stable_stop


def test_two_seconds_of_fresh_low_motion_passes() -> None:
    start = datetime.now(UTC)
    samples = [
        MotionSample(start + timedelta(milliseconds=100 * index), 0.01, 0.01, 0.01)
        for index in range(22)
    ]
    assert stable_stop(samples, start, start + timedelta(milliseconds=2200))


def test_motion_or_sparse_samples_fail_closed() -> None:
    start = datetime.now(UTC)
    samples = [
        MotionSample(start + timedelta(milliseconds=100 * index), 0.01, 0.01, 0.01)
        for index in range(22)
    ]
    samples[10] = MotionSample(samples[10].at, 0.5, 0.01, 0.01)
    assert not stable_stop(samples, start, start + timedelta(milliseconds=2200))
    sparse = [
        MotionSample(start, 0.0, 0.0, 0.0),
        MotionSample(start + timedelta(seconds=2), 0.0, 0.0, 0.0),
    ]
    assert not stable_stop(sparse, start, start + timedelta(seconds=2))


def test_rotating_robot_is_not_stopped() -> None:
    start = datetime.now(UTC)
    samples = [
        MotionSample(start + timedelta(milliseconds=100 * index), 0.0, 0.0, 0.1)
        for index in range(22)
    ]
    assert not stable_stop(samples, start, start + timedelta(milliseconds=2200))
