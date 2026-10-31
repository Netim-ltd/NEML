# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Pure perception logic: the camera egress gate and the depth reduction.

NEML_SPEC.md SS17.2 closes this with one sentence:

    "Kamera akisi ham olarak swarm agina verilmez; robot uzerinde JPEG
     sikistirilir ve yalnizca talep uzerine gonderilir."

Two rules fall out of it and both live here so both can be tested without a
ROS graph:

  1. raw frames never leave the robot. The gate never returns a raw image; the
     node only ever publishes CompressedImage.
  2. "on request" means somebody is subscribed to the compressed topic right
     now. A subscriber IS the request - there is no separate handshake to get
     out of sync, and the moment the last operator closes the stream the robot
     stops encoding and stops spending WiFi.
"""

import math

import numpy as np


def should_send(
    subscriber_count: int,
    now_s: float,
    last_sent_s: float | None,
    max_rate_hz: float,
) -> bool:
    """True when a frame may be encoded and published.

    subscriber_count == 0 means nobody requested the stream, so the robot does
    not even pay for the JPEG encode. max_rate_hz caps what a subscriber can
    pull out of the swarm link; the camera itself runs at 15 Hz locally.
    """
    if subscriber_count <= 0:
        return False
    if max_rate_hz <= 0.0:
        return False
    if last_sent_s is None:
        return True
    return (now_s - last_sent_s) >= (1.0 / max_rate_hz)


def nearest_obstacle_m(
    depth_m: np.ndarray,
    min_valid_m: float = 0.07,
    max_valid_m: float = 3.0,
    roi_fraction: float = 0.5,
) -> float:
    """Closest valid depth sample in the centre region of the frame, metres.

    Returns +inf when nothing in range is visible, which is the honest answer
    and keeps callers from treating a blind camera as "clear at 0 m".

    Defaults are the realsense d405 usable range from SS13.3. The ROI is the
    centre box: a quadruped only has to care about what is in front of its
    body, and cropping first makes this cheap enough to run at 15 Hz on a Pi 5.
    """
    if depth_m.ndim != 2:
        raise ValueError("depth_m must be a 2-D array of metres")
    if not 0.0 < roi_fraction <= 1.0:
        raise ValueError("roi_fraction must be in (0, 1]")

    rows, cols = depth_m.shape
    r_half = max(1, int(rows * roi_fraction / 2))
    c_half = max(1, int(cols * roi_fraction / 2))
    roi = depth_m[
        max(0, rows // 2 - r_half) : rows // 2 + r_half,
        max(0, cols // 2 - c_half) : cols // 2 + c_half,
    ]

    valid = roi[np.isfinite(roi) & (roi >= min_valid_m) & (roi <= max_valid_m)]
    if valid.size == 0:
        return math.inf
    return float(valid.min())
