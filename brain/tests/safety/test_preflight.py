# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 5.1: no fresh, passing safety_checks row means no physical task."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from neml_brain.safety.preflight import (
    DEFAULT_MAX_AGE,
    SafetyCheckMissing,
    require_safety_checks,
)


def test_documented_default_is_twelve_hours() -> None:
    assert DEFAULT_MAX_AGE == timedelta(hours=12)


async def test_fresh_passing_row_allows_the_task(session_factory: Any, db: Any) -> None:
    performed_at = datetime.now(UTC) - timedelta(hours=1)
    db.safety_checks = [(True, True, True, performed_at)]
    assert await require_safety_checks(session_factory, "r-1") == performed_at


async def test_no_row_refuses(session_factory: Any) -> None:
    with pytest.raises(SafetyCheckMissing, match="no safety_checks row"):
        await require_safety_checks(session_factory, "r-1")


async def test_stale_row_refuses(session_factory: Any, db: Any) -> None:
    db.safety_checks = [(True, True, True, datetime.now(UTC) - timedelta(hours=13))]
    with pytest.raises(SafetyCheckMissing, match="older than"):
        await require_safety_checks(session_factory, "r-1")


@pytest.mark.parametrize("bad", [0, 1, 2])
async def test_a_failed_check_refuses(session_factory: Any, db: Any, bad: int) -> None:
    flags = [True, True, True]
    flags[bad] = False
    db.safety_checks = [(*flags, datetime.now(UTC) - timedelta(minutes=5))]
    with pytest.raises(SafetyCheckMissing, match="failed"):
        await require_safety_checks(session_factory, "r-1")


async def test_max_age_is_configurable(session_factory: Any, db: Any) -> None:
    db.safety_checks = [(True, True, True, datetime.now(UTC) - timedelta(hours=13))]
    assert await require_safety_checks(session_factory, "r-1", max_age=timedelta(hours=24))
