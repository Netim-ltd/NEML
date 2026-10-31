# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Learning record written after every task (SPEC 14.6)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

from neml_brain.llm.profiles import check_failure_mode
from neml_brain.platform.core import Scope
from neml_brain.platform.learning import Episode

from .discovery import SUCCESS_FLOOR, TaskProposal, repair_proposal

log = structlog.get_logger(__name__)


@dataclass(slots=True)
class TaskOutcome:
    """One row of `task_runs` (SPEC 7) plus the context used for tagging."""

    task_id: str
    attempt: int
    env: str  # sim | bench | tethered | free
    started_at: datetime
    ended_at: datetime
    outcome: str  # success | failure | aborted | timeout
    context: str = ""  # log excerpt handed to the failure_tag profile
    skill_key: str | None = None
    seed: int | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    rosbag_path: str | None = None
    tenant_id: str | None = None
    domain_id: str | None = None
    robot_type: str | None = None
    robot_id: str | None = None
    model_version: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.outcome == "success"


@dataclass(slots=True)
class LearningDeps:
    record_run: Callable[[TaskOutcome], Awaitable[None]]
    # SPEC 4.3/4.4: failure_tag is a guided_choice classification, 64 tokens.
    # The choice list lives in the profile (llm.profiles.FAILURE_MODES), never
    # here; check_failure_mode() below is what holds the caller to it.
    tag_failure: Callable[[str], Awaitable[str]]
    remember: Callable[[str, str, str], Awaitable[None]]  # source_kind, source_id, content
    update_skill_stats: Callable[[str, bool], Awaitable[float]]  # -> cumulative success rate
    create_task: Callable[[TaskProposal], Awaitable[str]]
    record_episode: Callable[[Episode], Awaitable[None]] | None = None


async def record_and_learn(
    deps: LearningDeps, outcome: TaskOutcome, now: datetime | None = None
) -> str | None:
    """SPEC 14.6 steps 1-5. Returns the failure tag when there is one."""
    now = now or datetime.now(UTC)

    # 1. the result goes into task_runs
    await deps.record_run(outcome)

    tag: str | None = None
    if not outcome.succeeded:
        # 2. tag the failure mode with the failure_tag profile. The tag is the
        # string skill_runs.failure_mode stores, so it is refused here rather
        # than written and found invalid at the column (owner decision 4).
        tag = check_failure_mode(await deps.tag_failure(outcome.context))
        # 3. tag + context chunked, embedded, written to memory_chunks
        await deps.remember("failure", outcome.task_id, f"[{tag}] {outcome.context}")

    # A trainable episode requires a scoped type and independently verified
    # sensor result. Free-form task text is never treated as a reward label.
    if (
        deps.record_episode is not None
        and outcome.tenant_id
        and outcome.domain_id
        and outcome.robot_type
    ):
        import hashlib

        raw_features = outcome.metrics.get("normalized_features", [])
        verified = outcome.metrics.get("sensor_verified") is True
        features = tuple(float(value) for value in raw_features)
        if features and all(-1 <= value <= 1 for value in features):
            episode = Episode(
                id=f"{outcome.task_id}:{outcome.attempt}",
                scope=Scope(outcome.tenant_id, outcome.domain_id),
                robot_type=outcome.robot_type,
                observed_at=outcome.ended_at,
                observation_hash=hashlib.sha256(outcome.context.encode()).hexdigest(),
                action=outcome.skill_key or "observe",
                outcome=outcome.outcome,
                reward=1.0 if outcome.succeeded else -1.0,
                failure_class=tag,
                quality=1.0 if verified else 0.0,
                features=features,
                robot_id=outcome.robot_id or "",
                model_version=outcome.model_version or "",
            )
            await deps.record_episode(episode)

    if outcome.skill_key is None:
        return tag

    # 4. the skill's cumulative success statistic is updated
    rate = await deps.update_skill_stats(outcome.skill_key, outcome.succeeded)

    # 5. below 70 % -> an automatic repair task (SPEC 14.2)
    if rate < SUCCESS_FLOOR:
        await deps.create_task(repair_proposal(outcome.skill_key, rate, now, tag))
        log.info("autonomy.repair_queued", skill_key=outcome.skill_key, rate=rate, tag=tag)

    return tag
