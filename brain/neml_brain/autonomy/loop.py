# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The 24/7 autonomy loop (SPEC 14.1), run as a systemd service."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import structlog

TICK_S = 5  # SPEC 14.1

log = structlog.get_logger(__name__)


@dataclass(slots=True)
class AutonomyDeps:
    """Collaborators the loop drives. They live in safety/, runtime/, db/ and
    agents/ - modules this one does not own, so they are handed in."""

    safety_preflight: Callable[[], Awaitable[None]]  # L0 checks, robot state
    budget_ok: Callable[[], Awaitable[bool]]  # SPEC 14.4
    sleep_until_budget_reset: Callable[[], Awaitable[None]]  # 00:00 TRT
    discover_tasks: Callable[[], Awaitable[Any]]  # SPEC 14.2
    pick_next_task: Callable[[], Awaitable[Any | None]]  # priority order
    idle_policy: Callable[[], Awaitable[Any]]  # SPEC 14.5
    execute: Callable[[Any], Awaitable[Any]]  # LangGraph
    record_and_learn: Callable[[Any], Awaitable[Any]]  # SPEC 14.6
    on_safety_failure: Callable[[BaseException], Awaitable[None]]


async def autonomy_loop(
    deps: AutonomyDeps,
    *,
    stop: asyncio.Event | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """SPEC 14.1 exactly. Runs forever; only cancellation gets out.

    Two rules pull against each other and both hold here: the service must
    survive every exception without exiting, and a safety failure must never be
    swallowed. So a failed preflight is escalated through `on_safety_failure`
    and the tick ends right there - nothing is discovered, picked or executed
    on a tick whose safety gate did not pass. Only the process stays up.
    """
    while stop is None or not stop.is_set():
        try:
            await deps.safety_preflight()
        except Exception as exc:  # noqa: BLE001 - an unverifiable gate is a failed gate
            log.error("autonomy.safety_failed", error=str(exc), exc_info=exc)
            try:
                await deps.on_safety_failure(exc)
            except Exception as esc:  # noqa: BLE001
                log.error("autonomy.escalation_failed", error=str(esc))
            await sleep(TICK_S)
            continue

        try:
            if not await deps.budget_ok():  # SPEC 14.4
                await deps.sleep_until_budget_reset()
                continue

            await deps.discover_tasks()  # SPEC 14.2
            task = await deps.pick_next_task()
            if task is None:
                await deps.idle_policy()  # SPEC 14.5
                continue

            await deps.execute(task)
            await deps.record_and_learn(task)  # SPEC 14.6
        except Exception as exc:  # noqa: BLE001 - 24/7 service, one bad task is not fatal
            log.error("autonomy.tick_failed", error=str(exc), exc_info=exc)

        await sleep(TICK_S)
