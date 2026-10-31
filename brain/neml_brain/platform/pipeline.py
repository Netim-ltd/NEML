# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""One bounded training cycle. Physical deployment remains a separate approval flow."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from neml_brain.platform.artifacts import ModelArtifacts
from neml_brain.platform.core import Scope
from neml_brain.platform.learning import (
    AcceptanceThresholds,
    CandidateMetrics,
    Deployment,
    Episode,
    ModelBudgetTier,
    NightJob,
    allowed_model_budget,
    candidate_accepted,
    in_night_window,
    select_episodes,
)
from neml_brain.platform.policy import LinearPolicy, PolicySample
from neml_brain.platform.robots import ModelCard, ModelRegistry


class EpisodeSource(Protocol):
    async def list_for_training(self, scope: Scope, robot_type: str) -> list[Episode]: ...

    async def validated_missions(self, scope: Scope, robot_type: str) -> int: ...


class ModelMetadataStore(Protocol):
    async def save_model(self, card: ModelCard, artifact_path: str) -> None: ...


class ScenarioEvaluator(Protocol):
    async def evaluate(
        self, scope: Scope, robot_type: str, policy: LinearPolicy
    ) -> CandidateMetrics: ...


class FeatureEncoder(Protocol):
    def encode(self, episode: Episode) -> tuple[float, ...]: ...


class StoredFeatures:
    def encode(self, episode: Episode) -> tuple[float, ...]:
        if not episode.features:
            raise ValueError("episode has no normalized feature vector")
        return episode.features


@dataclass(frozen=True)
class TrainingOutcome:
    accepted: bool
    reason: str
    deployment: Deployment | None
    card: ModelCard | None


class NightPipeline:
    def __init__(
        self,
        source: EpisodeSource,
        evaluator: ScenarioEvaluator,
        encoder: FeatureEncoder,
        registry: ModelRegistry,
        thresholds: AcceptanceThresholds,
        artifacts: ModelArtifacts,
        model_store: ModelMetadataStore,
        budget_tiers: tuple[ModelBudgetTier, ...],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.source = source
        self.evaluator = evaluator
        self.encoder = encoder
        self.registry = registry
        self.thresholds = thresholds
        self.artifacts = artifacts
        self.model_store = model_store
        self.budget_tiers = budget_tiers
        self.clock = clock

    async def run(
        self,
        scope: Scope,
        base: LinearPolicy,
        previous_version: str,
        candidate_version: str,
        *,
        now: datetime | None = None,
    ) -> TrainingOutcome:
        started = now or self.clock()
        if not in_night_window(started):
            raise PermissionError("training is outside the night window")
        job = NightJob(scope, base.robot_type, started)
        episodes = select_episodes(
            await self.source.list_for_training(scope, base.robot_type), scope, base.robot_type
        )
        if len(episodes) < 20:
            return TrainingOutcome(False, "fewer than 20 quality episodes", None, None)
        # Keep previous experience in every incremental update. The caller's
        # source must include the retained replay set and regression corpus.
        samples = [PolicySample(self.encoder.encode(ep), ep.action, ep.reward) for ep in episodes]
        candidate = base.update(samples)
        metrics = await self.evaluator.evaluate(scope, base.robot_type, candidate)
        if not candidate_accepted(metrics, self.thresholds):
            return TrainingOutcome(False, "simulation or regression threshold failed", None, None)
        if job.must_cancel(self.clock()):
            return TrainingOutcome(False, "night window closed before publication", None, None)
        artifact = candidate.to_bytes()
        missions = await self.source.validated_missions(scope, base.robot_type)
        tier = allowed_model_budget(missions, self.budget_tiers)
        if len(artifact) > tier.max_model_mb * 1024 * 1024:
            return TrainingOutcome(False, "earned model size budget exceeded", None, None)
        card = ModelCard(
            scope=scope,
            robot_type=base.robot_type,
            version=candidate_version,
            artifact_sha256=hashlib.sha256(artifact).hexdigest(),
            signature=self.registry.sign(scope, base.robot_type, candidate_version, artifact),
            training_start=min(ep.observed_at for ep in episodes),
            training_end=max(ep.observed_at for ep in episodes),
            metrics={
                "sim_success": metrics.sim_success,
                "regression_success": metrics.regression_success,
                "reality_gap": metrics.reality_gap,
            },
            rollback_version=previous_version,
        )
        self.registry.add(card, artifact)
        path = self.artifacts.put(scope, base.robot_type, candidate_version, artifact)
        await self.model_store.save_model(card, str(path))
        deployment = Deployment(scope, base.robot_type, candidate_version, previous_version)
        return TrainingOutcome(True, "candidate validated in simulation", deployment, card)
