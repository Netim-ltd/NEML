# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 5.1 preflight: neml-brain refuses to start a physical task without a
fresh, passing `safety_checks` row for that robot.

The refusal is enforced here in code, not in a prompt. Every physical entry
point calls require_safety_checks() before it touches hardware.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from neml_brain.api.metrics import SAFETY_CHECK_AGE_HOURS  # SPEC 18.3, declared once
from neml_brain.runtime.audit import SessionFactory

# ponytail: "current working session" is modelled as a max age, not a session id,
# because safety_checks (SPEC 7) has no session column. Ceiling: a shift longer than
# MAX_AGE forces a re-test mid-shift. Upgrade path: add session_id to safety_checks
# and match on the open session instead of the clock.
DEFAULT_MAX_AGE = timedelta(hours=12)

_LATEST = text(
    "SELECT estop_ok, watchdog_ok, current_limit_ok, performed_at FROM safety_checks"
    " WHERE robot_id = :robot_id ORDER BY performed_at DESC LIMIT 1"
)


class SafetyCheckMissing(PermissionError):
    """No usable e-stop / watchdog / current-limit record. Physical work is refused."""


async def require_safety_checks(
    session_factory: SessionFactory,
    robot_id: str,
    *,
    max_age: timedelta = DEFAULT_MAX_AGE,
) -> datetime:
    """Return the timestamp of the passing check, or refuse.

    The *newest* row decides: a later failing test invalidates an earlier pass.
    """
    async with session_factory() as session:
        row = (await session.execute(_LATEST, {"robot_id": robot_id})).first()
    if row is None:
        raise SafetyCheckMissing(f"no safety_checks row for robot {robot_id}")
    estop_ok, watchdog_ok, current_limit_ok = bool(row[0]), bool(row[1]), bool(row[2])
    performed_at: datetime = row[3]
    age = datetime.now(UTC) - performed_at
    SAFETY_CHECK_AGE_HOURS.labels(robot_id).set(age.total_seconds() / 3600)
    if age > max_age:
        raise SafetyCheckMissing(f"safety_checks for {robot_id} is {age} old, older than {max_age}")
    failed = [
        name
        for name, ok in (
            ("estop_ok", estop_ok),
            ("watchdog_ok", watchdog_ok),
            ("current_limit_ok", current_limit_ok),
        )
        if not ok
    ]
    if failed:
        raise SafetyCheckMissing(f"safety_checks for {robot_id} failed: {', '.join(failed)}")
    return performed_at
