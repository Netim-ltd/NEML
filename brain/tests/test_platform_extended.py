# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Platform policy, artifact, scenario, and tenant isolation contract tests."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from neml_brain.platform.artifacts import ModelArtifacts
from neml_brain.platform.config import load_config
from neml_brain.platform.core import Scope
from neml_brain.platform.edge import DeploymentTicket, EdgeRuntime, sign_ticket
from neml_brain.platform.policy import LinearPolicy, PolicySample
from neml_brain.platform.robots import HomeRobot, ModelCard, ModelRegistry
from neml_brain.platform.scenarios import HOME_SCENARIOS, ScenarioEvaluator


def test_policy_round_trip_and_bounded_learning() -> None:
    policy = LinearPolicy.empty("home_v1", ("navigate", "stop"), 2)
    samples = [PolicySample((0.0, 1.0), "stop", 1.0)] * 30
    trained = policy.update(samples)
    assert trained.choose((0.0, 1.0)) == "stop"
    assert LinearPolicy.from_bytes(trained.to_bytes()) == trained
    with pytest.raises(ValueError):
        trained.choose((5.0, 0.0))


def test_artifacts_are_scoped_and_immutable(tmp_path) -> None:
    store = ModelArtifacts(tmp_path)
    first = Scope("company_a", "home")
    second = Scope("company_b", "home")
    path = store.put(first, "home_v1", "v1", b"model")
    assert store.get(first, "home_v1", "v1", hashlib.sha256(b"model").hexdigest()) == b"model"
    assert path != store._path(second, "home_v1", "v1")
    with pytest.raises(FileExistsError):
        store.put(first, "home_v1", "v1", b"different")


def test_platform_config_is_valid() -> None:
    from pathlib import Path

    config = load_config(Path(__file__).resolve().parents[2] / "config" / "platform.yaml")
    assert config.max_first_prototype_usd == 50
    assert config.domains["home"]["require_human_model_deployment"]


@pytest.mark.asyncio
async def test_scenario_requires_candidate_attestation() -> None:
    scope = Scope("company_a", "home")
    policy = LinearPolicy.empty("home_v1", ("navigate", "stop"), 2)

    class WrongPhysics:
        async def run_policy(self, scope, robot_type, model_sha256):
            return {"model_sha256": "other", "success_rate": 1.0, "reality_gap": 0.0}

    evaluator = ScenarioEvaluator(HOME_SCENARIOS, HOME_SCENARIOS, WrongPhysics())
    with pytest.raises(PermissionError):
        await evaluator.evaluate(scope, "home_v1", policy)


def test_edge_rejects_unapproved_and_wrong_tenant_models(tmp_path) -> None:
    scope = Scope("company_a", "home")
    registry = ModelRegistry(b"k" * 32)
    policy = LinearPolicy.empty("home_v1", ("navigate", "stop"), 2)
    artifact = policy.to_bytes()
    now = datetime.now(UTC)
    card = ModelCard(
        scope,
        "home_v1",
        "v1",
        hashlib.sha256(artifact).hexdigest(),
        registry.sign(scope, "home_v1", "v1", artifact),
        now,
        now,
        {"sim_success": 1.0},
        None,
    )
    edge = EdgeRuntime(
        scope, "r1", "home_v1", registry.public_key_bytes(), tmp_path, HomeRobot().envelope
    )
    ticket = DeploymentTicket(
        scope, "r1", "home_v1", "v1", "canary", None, now + timedelta(minutes=5), ""
    )
    ticket = sign_ticket(ticket, registry._private)
    with pytest.raises(PermissionError):
        edge.install(card, artifact, ticket)
    approved = DeploymentTicket(
        scope, "r1", "home_v1", "v1", "canary", "approval-1", now + timedelta(minutes=5), ""
    )
    approved = sign_ticket(approved, registry._private)
    assert edge.install(card, artifact, approved) == "v1"
    assert edge.load_active(card) == "v1"
    with pytest.raises(PermissionError):
        edge.authorize_actuator(speed_mps=1.0, force_n=1, zone="home_clear", estop=False)
