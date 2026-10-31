# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Night pipeline acceptance and cutoff contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from neml_brain.platform.artifacts import ModelArtifacts
from neml_brain.platform.core import Scope
from neml_brain.platform.learning import (
    AcceptanceThresholds,
    CandidateMetrics,
    Episode,
    ModelBudgetTier,
)
from neml_brain.platform.pipeline import NightPipeline, StoredFeatures
from neml_brain.platform.policy import LinearPolicy
from neml_brain.platform.robots import ModelRegistry


@pytest.mark.asyncio
async def test_night_pipeline_registers_only_sim_validated_candidate(tmp_path) -> None:
    scope = Scope("company_a", "home")
    start = datetime(2026, 9, 29, 22, 0, tzinfo=UTC)  # 01:00 Istanbul
    episodes = [
        Episode(
            f"e{i}",
            scope,
            "home_v1",
            start - timedelta(minutes=i),
            f"observation-{i}",
            "stop",
            "success",
            1.0,
            None,
            1.0,
            (0.0, 1.0),
            "r1",
            "v1",
        )
        for i in range(25)
    ]

    class Source:
        async def list_for_training(self, scope, robot_type):
            return episodes

        async def validated_missions(self, scope, robot_type):
            return 25

    class Evaluator:
        async def evaluate(self, scope, robot_type, policy):
            assert policy.choose((0.0, 1.0)) == "stop"
            return CandidateMetrics(0.98, 0.99, 0.1)

    class Metadata:
        def __init__(self):
            self.saved = []

        async def save_model(self, card, artifact_path):
            self.saved.append((card, artifact_path))

    metadata = Metadata()
    registry = ModelRegistry(b"k" * 32)
    pipeline = NightPipeline(
        Source(),
        Evaluator(),
        StoredFeatures(),
        registry,
        AcceptanceThresholds(),
        ModelArtifacts(tmp_path),
        metadata,
        (ModelBudgetTier("initial", 25, 0),),
        clock=lambda: start,
    )
    base = LinearPolicy.empty("home_v1", ("navigate", "stop"), 2)
    outcome = await pipeline.run(scope, base, "v1", "v2", now=start)
    assert outcome.accepted
    assert outcome.card is not None
    assert registry.get(scope, "home_v1", "v2") == outcome.card
    assert len(metadata.saved) == 1


@pytest.mark.asyncio
async def test_night_pipeline_rejects_daytime(tmp_path) -> None:
    class Source:
        async def list_for_training(self, scope, robot_type):
            raise AssertionError("source must not be queried outside the window")

    class Unused:
        async def evaluate(self, scope, robot_type, policy):
            raise AssertionError("evaluator must not run outside the window")

        async def save_model(self, card, artifact_path):
            raise AssertionError("model must not be saved outside the window")

    instant = datetime(2026, 9, 30, 9, 0, tzinfo=UTC)
    pipeline = NightPipeline(
        Source(),
        Unused(),
        StoredFeatures(),
        ModelRegistry(b"k" * 32),
        AcceptanceThresholds(),
        ModelArtifacts(tmp_path),
        Unused(),
        (ModelBudgetTier("initial", 25, 0),),
        clock=lambda: instant,
    )
    with pytest.raises(PermissionError):
        await pipeline.run(
            Scope("company_a", "home"),
            LinearPolicy.empty("home_v1", ("navigate", "stop"), 2),
            "v1",
            "v2",
            now=instant,
        )
