# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The SS17.2 egress rule and the depth reduction, tested without a ROS graph."""

import math

import numpy as np
import pytest

from neml_perception.gate import nearest_obstacle_m, should_send


def test_no_subscriber_means_no_encode():
    """The whole point of SS17.2: nothing leaves the robot unasked."""
    assert not should_send(0, now_s=100.0, last_sent_s=None, max_rate_hz=2.0)


def test_first_frame_goes_out_immediately_once_requested():
    assert should_send(1, now_s=100.0, last_sent_s=None, max_rate_hz=2.0)


def test_rate_limit_holds_between_frames():
    assert not should_send(1, now_s=100.4, last_sent_s=100.0, max_rate_hz=2.0)
    assert should_send(1, now_s=100.5, last_sent_s=100.0, max_rate_hz=2.0)


def test_zero_rate_disables_the_stream():
    """A rate of 0 is the kill switch, not "unlimited"."""
    assert not should_send(5, now_s=100.0, last_sent_s=None, max_rate_hz=0.0)


def test_nearest_obstacle_finds_the_close_sample():
    depth = np.full((40, 60), 2.0, dtype=np.float32)
    depth[20, 30] = 0.35
    assert nearest_obstacle_m(depth) == pytest.approx(0.35)


def test_samples_outside_the_roi_are_ignored():
    depth = np.full((40, 60), 2.0, dtype=np.float32)
    depth[0, 0] = 0.20
    assert nearest_obstacle_m(depth, roi_fraction=0.5) == pytest.approx(2.0)


def test_out_of_range_and_nan_are_not_obstacles():
    depth = np.full((40, 60), np.nan, dtype=np.float32)
    depth[20, 30] = 0.01   # below the d405 minimum
    depth[20, 31] = 9.0    # beyond the d405 maximum
    depth[20, 32] = 0.0    # the "no return" value realsense writes
    assert nearest_obstacle_m(depth) == math.inf


def test_blind_frame_reports_infinity_not_zero():
    assert nearest_obstacle_m(np.zeros((8, 8), dtype=np.float32)) == math.inf


def test_rejects_non_depth_input():
    with pytest.raises(ValueError):
        nearest_obstacle_m(np.zeros((4, 4, 3), dtype=np.float32))
    with pytest.raises(ValueError):
        nearest_obstacle_m(np.zeros((4, 4), dtype=np.float32), roi_fraction=0.0)
