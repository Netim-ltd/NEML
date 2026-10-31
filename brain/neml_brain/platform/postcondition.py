# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Independent measured stop criterion for a robot recovery label."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

MIN_STABLE = timedelta(seconds=2)
MAX_GAP = timedelta(milliseconds=500)
MAX_JOINT_RAD_S = 0.02
MAX_BODY_M_S = 0.02
MAX_BODY_RAD_S = 0.02


@dataclass(frozen=True)
class MotionSample:
    at: datetime
    max_joint_rad_s: float
    body_m_s: float
    body_rad_s: float


def stable_stop(samples: Sequence[MotionSample], report_at: datetime, now: datetime) -> bool:
    """Require a fresh continuous 2 s window after the reported recovery."""
    if report_at.tzinfo is None or now.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    relevant = sorted(
        (item for item in samples if report_at <= item.at <= now), key=lambda item: item.at
    )
    if not relevant or now - relevant[-1].at > MAX_GAP:
        return False
    start: datetime | None = None
    previous: datetime | None = None
    for item in relevant:
        values = (item.max_joint_rad_s, item.body_m_s, item.body_rad_s)
        safe = (
            all(math.isfinite(value) and value >= 0 for value in values)
            and item.max_joint_rad_s <= MAX_JOINT_RAD_S
            and item.body_m_s <= MAX_BODY_M_S
            and item.body_rad_s <= MAX_BODY_RAD_S
        )
        if not safe or previous is not None and item.at - previous > MAX_GAP:
            start = None
        if safe and start is None:
            start = item.at
        previous = item.at
    return start is not None and relevant[-1].at - start >= MIN_STABLE
