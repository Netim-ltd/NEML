# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Second look at finished work (ADR-014).

A task judged done last week is re-judged against today's criteria and the
numbers it stored. Anything that no longer passes is reopened, so a threshold
that tightened, or a measurement that was wrong, cannot stay buried as
"succeeded". The reopen is a state change plus a reason; the task then goes
through the normal queue, gates and judge again.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

import structlog

from .judge import RunFacts, TaskFacts, judge

log = structlog.get_logger(__name__)


class ReviewRepo(Protocol):
    async def recent_done(self, days: int) -> Sequence[tuple[TaskFacts, RunFacts]]: ...
    async def reopen(self, task_id: str, reasons: Sequence[str]) -> None: ...


async def review_completed(repo: ReviewRepo, days: int = 7) -> list[str]:
    """Reopen every recently-done task that fails today's judgement; returns ids."""
    reopened: list[str] = []
    for task, run in await repo.recent_done(days):
        verdict = judge(task, run)
        if verdict.done:
            continue
        await repo.reopen(task.task_id, verdict.reasons)
        reopened.append(task.task_id)
        log.warning("autonomy.reopened", task_id=task.task_id, reasons=list(verdict.reasons))
    return reopened
