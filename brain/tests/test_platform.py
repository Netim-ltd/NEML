# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Cross-phase decision tests; run with the final consolidated test pass."""

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from neml_brain.platform.adapters import (
    EXAMPLE_SCENARIOS,
    MockGazeboEnvironment,
    MockMcpAdapter,
    ToolCall,
)
from neml_brain.platform.core import Command, Event, EventLedger, Hierarchy, Rank, Scope, Unit
from neml_brain.platform.design import BomLine, DesignPackage, detect_gap, request_parts
from neml_brain.platform.learning import (
    AcceptanceThresholds,
    CandidateMetrics,
    Deployment,
    Episode,
    ModelBudgetTier,
    Stage,
    allowed_model_budget,
    in_night_window,
    select_episodes,
)
from neml_brain.platform.robots import (
    FieldRobot,
    HomeRobot,
    ModelCard,
    ModelRegistry,
    PluginRegistry,
)


def test_hierarchy_is_tenant_scoped_and_degrades() -> None:
    home = Scope("firm_a", "home")
    other = Scope("firm_b", "home")
    units = [
        Unit("strategy", home, Rank.STRATEGY, None),
        Unit("domain", home, Rank.DOMAIN, "strategy"),
        Unit("team", home, Rank.TEAM, "domain"),
        Unit("robot", home, Rank.ROBOT, "team"),
    ]
    tree = Hierarchy(units)
    now = datetime.now(UTC)
    good = Command("c1", home, "team", "robot", 3, now + timedelta(seconds=5), "inspect")
    assert tree.route(good, epoch=3, now=now).id == "robot"
    assert tree.safe_action("robot", parent_online=False) == "hold_position"
    with pytest.raises(PermissionError):
        tree.route(Command("c2", other, "team", "robot", 3, good.expires_at, "inspect"), epoch=3)
    with pytest.raises(PermissionError):
        tree.route(good, epoch=4, now=now)


def test_events_are_idempotent_and_scoped() -> None:
    scope = Scope("a", "field")
    event = Event("e1", scope, "EpisodeRecorded", "r1", datetime.now(UTC), {"ok": True})
    ledger = EventLedger()
    assert ledger.append(event)
    assert not ledger.append(event)
    assert ledger.read(Scope("b", "field")) == []


def test_plugins_and_safety_envelope() -> None:
    registry = PluginRegistry()
    registry.register(HomeRobot())
    registry.register(FieldRobot())
    assert len(registry.capable(frozenset({"inspect_crop"}))) == 1
    with pytest.raises(PermissionError):
        HomeRobot().envelope.constrain(speed_mps=0.3, force_n=1, zone="home_clear", estop=False)
    assert detect_gap(registry, Scope("a", "field"), "t1", frozenset({"fly"}))


def test_model_registry_checks_signature_and_scope() -> None:
    registry = ModelRegistry(b"a" * 32)
    artifact = b"example ONNX bytes"
    scope = Scope("firm_a", "field")
    now = datetime.now(UTC)
    card = ModelCard(
        scope,
        "field_v1",
        "v1",
        hashlib.sha256(artifact).hexdigest(),
        registry.sign(scope, "field_v1", "v1", artifact),
        now,
        now,
        {"sim_success": 0.99},
        None,
    )
    registry.add(card, artifact)
    assert registry.get(scope, "field_v1", "v1") == card
    with pytest.raises(KeyError):
        registry.get(Scope("firm_b", "field"), "field_v1", "v1")
    with pytest.raises(ValueError):
        registry.add(card, b"tampered")


def test_night_candidate_and_human_approval() -> None:
    scope = Scope("a", "field")
    assert in_night_window(datetime(2026, 9, 30, 1, 0, tzinfo=UTC))
    episode = Episode("e1", scope, "field_v1", datetime.now(UTC), "hash", "go", "ok", 1, None, 1)
    assert select_episodes([episode, episode], scope, "field_v1") == [episode]
    deploy = Deployment(scope, "field_v1", "v2", "v1")
    deploy = deploy.advance(metrics=CandidateMetrics(0.99, 0.99, 0.1))
    assert deploy.stage is Stage.SIM_VALIDATED
    with pytest.raises(PermissionError):
        deploy.advance()
    deploy = deploy.advance(human_approval_id="approval-canary")
    assert deploy.stage is Stage.CANARY_PENDING
    deploy = deploy.acknowledge("v2")
    rollback = deploy.advance(canary_failure_rate=0.5)
    assert rollback.stage is Stage.ROLLBACK_PENDING
    assert rollback.acknowledge("v1").stage is Stage.ROLLED_BACK
    fleet = deploy.advance(canary_failure_rate=0, human_approval_id="approval-fleet")
    assert fleet.stage is Stage.FLEET_PENDING
    assert fleet.acknowledge("v2").stage is Stage.FLEET
    assert AcceptanceThresholds().max_reality_gap == 0.2


def test_budget_and_purchase_are_bounded() -> None:
    tiers = (ModelBudgetTier("initial", 25, 0), ModelBudgetTier("proven", 50, 100))
    assert allowed_model_budget(99, tiers).name == "initial"
    assert allowed_model_budget(100, tiers).name == "proven"
    scope = Scope("a", "field")
    gap = detect_gap(PluginRegistry(), scope, "task", frozenset({"fly"}))
    assert gap is not None
    package = DesignPackage(
        gap,
        "req.md",
        "body.FCStd",
        "pcb.kicad_pcb",
        "fw.c",
        "sim.json",
        (BomLine("motor", 2, Decimal("20"), "alt"),),
    )
    assert package.affordable_first_prototype()

    class Verifier:
        def approved(self, approval_id: str, scope: Scope, subject_id: str) -> bool:
            return approval_id == "approved"

    class Sender:
        def send(self, recipient: str, package: DesignPackage) -> str:
            return "message-id"

    with pytest.raises(PermissionError):
        request_parts(
            package,
            recipient="owner@example.com",
            allowed_recipients=frozenset({"owner@example.com"}),
            approval_id="pending",
            verifier=Verifier(),
            sender=Sender(),
        )
    assert (
        request_parts(
            package,
            recipient="owner@example.com",
            allowed_recipients=frozenset({"owner@example.com"}),
            approval_id="approved",
            verifier=Verifier(),
            sender=Sender(),
        )
        == "message-id"
    )


@pytest.mark.asyncio
async def test_mock_tools_and_simulation() -> None:
    scope = Scope("a", "home")
    cad = MockMcpAdapter("freecad")
    result = await cad.invoke(ToolCall(scope, "freecad", "export", "hash", 5), {})
    assert result["mock"] is True
    sim = MockGazeboEnvironment(EXAMPLE_SCENARIOS)
    assert (await sim.run(scope, "home_person_nearby", "v1"))["safety_violation"] == 0
