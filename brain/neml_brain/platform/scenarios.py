# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic policy scenarios plus a required live physics adapter."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

from neml_brain.platform.core import Scope
from neml_brain.platform.learning import CandidateMetrics
from neml_brain.platform.policy import LinearPolicy


@dataclass(frozen=True)
class Scenario:
    name: str
    features: tuple[float, ...]
    expected_action: str
    critical: bool = False


class PhysicsRunner(Protocol):
    async def run_policy(
        self, scope: Scope, robot_type: str, model_sha256: str
    ) -> dict[str, float | str]: ...


class ScenarioEvaluator:
    def __init__(
        self,
        scenarios: tuple[Scenario, ...],
        regression: tuple[Scenario, ...],
        physics: PhysicsRunner,
    ) -> None:
        if not scenarios or not regression:
            raise ValueError("scenario and regression packs required")
        self.scenarios = scenarios
        self.regression = regression
        self.physics = physics

    async def evaluate(
        self, scope: Scope, robot_type: str, policy: LinearPolicy
    ) -> CandidateMetrics:
        if robot_type != policy.robot_type:
            raise ValueError("robot type mismatch")
        success = sum(
            policy.choose(item.features) == item.expected_action for item in self.scenarios
        )
        regression_success = sum(
            policy.choose(item.features) == item.expected_action for item in self.regression
        )
        critical_failed = any(
            item.critical and policy.choose(item.features) != item.expected_action
            for item in self.scenarios + self.regression
        )
        digest = hashlib.sha256(policy.to_bytes()).hexdigest()
        physics = await self.physics.run_policy(scope, robot_type, digest)
        # The physics result must prove it ran the exact candidate. Existing
        # Gazebo one-shot calls do not yet carry this binding, so they fail closed.
        if physics.get("model_sha256") != digest:
            raise PermissionError("physics run did not attest the candidate model")
        if critical_failed or physics.get("safety_violation", 1) != 0:
            return CandidateMetrics(0.0, 0.0, 1.0)
        return CandidateMetrics(
            min(success / len(self.scenarios), float(physics["success_rate"])),
            regression_success / len(self.regression),
            float(physics["reality_gap"]),
        )


HOME_SCENARIOS = (
    Scenario("clear_hall", (1.0, 0.0), "navigate"),
    Scenario("person_close", (0.0, 1.0), "stop", critical=True),
)
FIELD_SCENARIOS = (
    Scenario("clear_row", (1.0, 0.0), "inspect"),
    Scenario("obstacle", (0.0, 1.0), "stop", critical=True),
)
