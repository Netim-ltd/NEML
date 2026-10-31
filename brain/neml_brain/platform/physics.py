# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""PhysicsRunner backed by neml-mcp-sim: runs the exact candidate in Gazebo."""

from __future__ import annotations

import asyncio
import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from neml_brain.platform.core import Scope
from neml_brain.platform.policy import LinearPolicy

REQUIRED_METRICS = ("success_rate", "reality_gap", "safety_violation")


class McpCaller(Protocol):
    async def call(
        self,
        server: str,
        tool: str,
        arguments: dict[str, Any] | None = None,
        timeout_s: float | None = None,
    ) -> Any: ...


@dataclass(frozen=True)
class PhysicsScenario:
    world_id: str
    urdf_path: str
    seed: int = 1
    duration_s: float = 30.0
    reference_x_m: float | None = None  # distance a real robot covered; sets reality_gap
    spawn_z_m: float = 0.0  # drop height; a wheeled body wants a few cm of clearance


class GazeboPhysicsRunner:
    """Stages the candidate policy, runs it in the sim, returns attested metrics.

    The policy bytes are looked up by sha256, so the file the simulator loads is the
    one that was hashed. The sim must echo that hash back from `get_metrics`; without
    it `ScenarioEvaluator` fails closed.
    """

    def __init__(
        self,
        mcp: McpCaller,
        policies: dict[str, LinearPolicy],
        scenarios: dict[str, PhysicsScenario],
        stage_dir: Path | None = None,
        timeout_s: float = 600.0,
    ) -> None:
        self.mcp = mcp
        self.policies = policies  # sha256 -> policy; filled by the evaluator's caller
        self.scenarios = scenarios
        self.stage_dir = stage_dir or Path(tempfile.gettempdir()) / "neml_policies"
        self.timeout_s = timeout_s

    def register(self, policy: LinearPolicy) -> str:
        digest = hashlib.sha256(policy.to_bytes()).hexdigest()
        self.policies[digest] = policy
        return digest

    async def run_policy(self, scope: Scope, robot_type: str, model_sha256: str) -> dict[str, Any]:
        policy = self.policies.get(model_sha256)
        if policy is None or policy.robot_type != robot_type:
            raise PermissionError("candidate policy was not registered for this robot type")
        scenario = self.scenarios.get(robot_type)
        if scenario is None:
            raise ValueError(f"no physics scenario for robot type '{robot_type}'")
        self.stage_dir.mkdir(parents=True, exist_ok=True)
        path = self.stage_dir / f"{model_sha256}.json"
        path.write_bytes(policy.to_bytes())
        ns = f"cand_{model_sha256[:8]}"
        t = self.timeout_s
        world = await self.mcp.call(
            "sim",
            "load_world",
            {"world_id": scenario.world_id, "seed": scenario.seed, "profile": "fast"},
            t,
        )
        try:
            robot = await self.mcp.call(
                "sim",
                "spawn_robot",
                {
                    "urdf_path": scenario.urdf_path,
                    "pose": {
                        "x_m": 0.0,
                        "y_m": 0.0,
                        "z_m": scenario.spawn_z_m,
                        "roll_rad": 0.0,
                        "pitch_rad": 0.0,
                        "yaw_rad": 0.0,
                    },
                    "ns": ns,
                    "policy_path": str(path),
                },
                t,
            )
            await self.mcp.call(
                "sim",
                "run_until",
                {"condition": f"sim_time_s>={scenario.duration_s}", "timeout_s": t},
                t,
            )
            metrics = await self.mcp.call("sim", "get_metrics", {"robot": robot}, t)
        finally:
            await self.mcp.call("sim", "teardown", {"handle": world}, t)
        values = dict(metrics.get("values", {}))
        if metrics.get("deterministic") is False:
            raise RuntimeError("sim run flagged non-deterministic; result unusable (SPEC 11.2)")
        missing = [k for k in REQUIRED_METRICS if k not in values]
        if missing:
            raise ValueError(f"sim metrics missing {missing}")
        return {
            "model_sha256": str(metrics.get("policy_sha256", "")),
            "success_rate": float(values["success_rate"]),
            "reality_gap": self._gap(scenario, values),
            "safety_violation": float(values["safety_violation"]),
            "randomization": metrics.get("randomization") or {},  # SPEC 11.4 record of the run
        }

    @staticmethod
    def _gap(scenario: PhysicsScenario, values: dict[str, Any]) -> float:
        """|sim - real| / real distance when a real reference exists, else the sim's own gap."""
        ref = scenario.reference_x_m
        if ref is None or "x_m" not in values:
            return float(values["reality_gap"])
        return min(1.0, abs(float(values["x_m"]) - ref) / max(abs(ref), 1e-6))


class PooledPhysicsRunner:
    """Runs candidates concurrently over N independent sim servers.

    Each sim server holds one world (and, via GzRunner(partition=...), its own Gazebo
    transport partition), so parallelism comes from separate servers, not from
    sharing one. A call waits for a free runner; at most len(runners) run at once.
    """

    def __init__(self, runners: list[GazeboPhysicsRunner]) -> None:
        if not runners:
            raise ValueError("pool needs at least one runner")
        self._free: asyncio.Queue[GazeboPhysicsRunner] = asyncio.Queue()
        for runner in runners:
            self._free.put_nowait(runner)
        self.runners = runners

    def register(self, policy: LinearPolicy) -> str:
        digests = {runner.register(policy) for runner in self.runners}
        return digests.pop()

    async def run_policy(self, scope: Scope, robot_type: str, model_sha256: str) -> dict[str, Any]:
        runner = await self._free.get()
        try:
            return await runner.run_policy(scope, robot_type, model_sha256)
        finally:
            self._free.put_nowait(runner)
