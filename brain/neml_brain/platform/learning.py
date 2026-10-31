# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Episode selection, bounded night jobs, and staged deployment decisions."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, time
from enum import StrEnum
from zoneinfo import ZoneInfo

from neml_brain.platform.core import Scope

TZ = ZoneInfo("Europe/Istanbul")
WINDOW_START = time(23, 59)
WINDOW_END = time(4, 59)


def in_night_window(now: datetime) -> bool:
    local = now.astimezone(TZ).time()
    return local >= WINDOW_START or local < WINDOW_END


@dataclass(frozen=True)
class Episode:
    id: str
    scope: Scope
    robot_type: str
    observed_at: datetime
    observation_hash: str
    action: str
    outcome: str
    reward: float
    failure_class: str | None
    quality: float
    features: tuple[float, ...] = ()
    robot_id: str = ""
    model_version: str = ""

    def __post_init__(self) -> None:
        if not 0 <= self.quality <= 1 or not -1 <= self.reward <= 1:
            raise ValueError("episode quality/reward out of range")


def select_episodes(
    episodes: list[Episode], scope: Scope, robot_type: str, *, min_quality: float = 0.8
) -> list[Episode]:
    """Dedupe by observation/action/outcome while retaining critical failures."""
    selected: dict[str, Episode] = {}
    for episode in episodes:
        if episode.scope != scope or episode.robot_type != robot_type:
            continue
        if episode.quality < min_quality:
            continue
        key = hashlib.sha256(
            f"{episode.observation_hash}:{episode.action}:{episode.outcome}".encode()
        ).hexdigest()
        previous = selected.get(key)
        if previous is None or episode.failure_class and not previous.failure_class:
            selected[key] = episode
    return sorted(
        selected.values(), key=lambda item: (item.failure_class is None, item.observed_at)
    )


@dataclass(frozen=True)
class AcceptanceThresholds:
    min_sim_success: float = 0.9
    min_regression_success: float = 0.95
    max_reality_gap: float = 0.2
    max_canary_failure: float = 0.02


DEFAULT_THRESHOLDS = AcceptanceThresholds()


@dataclass(frozen=True)
class CandidateMetrics:
    sim_success: float
    regression_success: float
    reality_gap: float


def candidate_accepted(metrics: CandidateMetrics, thresholds: AcceptanceThresholds) -> bool:
    return (
        metrics.sim_success >= thresholds.min_sim_success
        and metrics.regression_success >= thresholds.min_regression_success
        and metrics.reality_gap <= thresholds.max_reality_gap
    )


class Stage(StrEnum):
    CANDIDATE = "candidate"
    SIM_VALIDATED = "sim_validated"
    CANARY_PENDING = "canary_pending"
    CANARY = "canary"
    FLEET_PENDING = "fleet_pending"
    FLEET = "fleet"
    ROLLBACK_PENDING = "rollback_pending"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True)
class Deployment:
    scope: Scope
    robot_type: str
    candidate_version: str
    previous_version: str
    stage: Stage = Stage.CANDIDATE

    def advance(
        self,
        *,
        metrics: CandidateMetrics | None = None,
        thresholds: AcceptanceThresholds = DEFAULT_THRESHOLDS,
        human_approval_id: str | None = None,
        canary_failure_rate: float | None = None,
    ) -> Deployment:
        if self.stage is Stage.CANDIDATE:
            if metrics is None or not candidate_accepted(metrics, thresholds):
                raise PermissionError("simulation/regression gate failed")
            next_stage = Stage.SIM_VALIDATED
        elif self.stage is Stage.SIM_VALIDATED:
            if not human_approval_id:
                raise PermissionError("canary deployment needs human approval")
            next_stage = Stage.CANARY_PENDING
        elif self.stage is Stage.CANARY:
            if canary_failure_rate is None:
                raise ValueError("canary metrics required")
            if canary_failure_rate > thresholds.max_canary_failure:
                next_stage = Stage.ROLLBACK_PENDING
            else:
                if not human_approval_id:
                    raise PermissionError("fleet deployment needs human approval")
                next_stage = Stage.FLEET_PENDING
        else:
            raise ValueError("terminal deployment stage")
        return Deployment(
            self.scope, self.robot_type, self.candidate_version, self.previous_version, next_stage
        )

    def acknowledge(self, applied_version: str) -> Deployment:
        """Only a robot-side acknowledgement completes physical stage changes."""
        transitions = {
            Stage.CANARY_PENDING: (self.candidate_version, Stage.CANARY),
            Stage.FLEET_PENDING: (self.candidate_version, Stage.FLEET),
            Stage.ROLLBACK_PENDING: (self.previous_version, Stage.ROLLED_BACK),
        }
        if self.stage not in transitions:
            raise ValueError("deployment has no pending robot update")
        expected, next_stage = transitions[self.stage]
        if applied_version != expected:
            raise PermissionError("robot acknowledged the wrong model version")
        return Deployment(
            self.scope, self.robot_type, self.candidate_version, self.previous_version, next_stage
        )


@dataclass(frozen=True)
class NightJob:
    scope: Scope
    robot_type: str
    started_at: datetime
    completed: bool = False

    def may_publish(self, now: datetime) -> bool:
        return self.completed and in_night_window(now)

    def must_cancel(self, now: datetime) -> bool:
        return not self.completed and not in_night_window(now)


@dataclass(frozen=True)
class ModelBudgetTier:
    name: str
    max_model_mb: int
    min_validated_missions: int


def allowed_model_budget(
    validated_missions: int, tiers: tuple[ModelBudgetTier, ...]
) -> ModelBudgetTier:
    """Choose the highest earned tier; invalid or empty policy fails closed."""
    if validated_missions < 0 or not tiers:
        raise ValueError("invalid budget policy")
    eligible = [tier for tier in tiers if validated_missions >= tier.min_validated_missions]
    if not eligible:
        raise PermissionError("no model budget tier earned")
    return max(eligible, key=lambda tier: tier.min_validated_missions)
