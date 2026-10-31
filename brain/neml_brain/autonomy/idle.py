# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Idle policy (SPEC 14.5). Empty queue never means idle waiting."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum

import structlog

BATTERY_FLOOR = 0.30  # SPEC 14.5 step 1: robots.battery_soc is 0..1
IDLE_SLEEP_S = 60  # SPEC 14.5 step 6

log = structlog.get_logger(__name__)


class IdleAction(StrEnum):
    """Which of the six steps actually did something."""

    CHARGING = "charging"
    EXPLORATION = "exploration"
    CALIBRATION = "calibration"
    MEMORY = "memory"
    SLEPT = "slept"


@dataclass(slots=True)
class IdleDeps:
    robot_batteries: Callable[[], Awaitable[Mapping[str, float]]]
    send_to_charger: Callable[[str], Awaitable[None]]  # sets robots.state = 'charging'
    make_exploration_task: Callable[[], Awaitable[bool]]  # SPEC 14.2 coverage gap
    make_calibration_task: Callable[[], Awaitable[bool]]  # stale calibration
    consolidate_memory: Callable[[], Awaitable[int]]  # chunks written, last 24 h failures
    budget_ok: Callable[[], Awaitable[bool]]  # SPEC 14.4


async def idle_policy(
    deps: IdleDeps,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> IdleAction:
    """SPEC 14.5, in order, first hit wins.

    The rule: never sit in an idle wait, never step outside the budget. Steps
    2-5 spend resources, so they are gated on the budget; step 1 is an energy
    action on a robot that is running out either way.
    """
    # 1. battery under 30 % -> charging station
    low = [rid for rid, soc in (await deps.robot_batteries()).items() if soc < BATTERY_FLOOR]
    if low:
        for robot_id in low:
            await deps.send_to_charger(robot_id)
        return IdleAction.CHARGING

    if not await deps.budget_ok():
        await sleep(IDLE_SLEEP_S)
        return IdleAction.SLEPT

    # 2. coverage gap -> exploration task
    if await deps.make_exploration_task():
        return IdleAction.EXPLORATION

    # 4. calibration gone stale -> calibration task
    if await deps.make_calibration_task():
        return IdleAction.CALIBRATION

    # 5. nothing else -> consolidate the last 24 h of failure logs into memory
    if await deps.consolidate_memory() > 0:
        return IdleAction.MEMORY

    # 6. that too is done -> 60 s sleep
    await sleep(IDLE_SLEEP_S)
    return IdleAction.SLEPT
