# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio
import hashlib

import pytest

from neml_brain.platform.physics import GazeboPhysicsRunner, PhysicsScenario
from neml_brain.platform.policy import LinearPolicy


class FakeMcp:
    def __init__(self, echo=True, values=None, det=True):
        self.calls, self.echo, self.det = [], echo, det
        self.values = values or {"success_rate": 0.9, "reality_gap": 0.1, "safety_violation": 0}

    async def call(self, server, tool, arguments=None, timeout_s=None):
        self.calls.append(tool)
        if tool == "spawn_robot":
            assert set(arguments["pose"]) == {
                "x_m",
                "y_m",
                "z_m",
                "roll_rad",
                "pitch_rad",
                "yaw_rad",
            }  # server.Pose(**pose) rejects anything else
            self.sha = hashlib.sha256(open(arguments["policy_path"], "rb").read()).hexdigest()
            return {"ns": arguments["ns"]}
        if tool == "get_metrics":
            return {
                "values": self.values,
                "deterministic": self.det,
                "policy_sha256": self.sha if self.echo else "",
            }
        return {"world_id": "w"}


def _runner(mcp, tmp_path):
    p = LinearPolicy.empty("home_v1", ("stop", "navigate"), 2)
    r = GazeboPhysicsRunner(mcp, {}, {"home_v1": PhysicsScenario("flat", "x.urdf")}, tmp_path)
    return r, r.register(p)


def test_attests_exact_candidate(tmp_path):
    m = FakeMcp()
    r, sha = _runner(m, tmp_path)
    out = asyncio.run(r.run_policy(None, "home_v1", sha))  # type: ignore[arg-type]
    assert out["model_sha256"] == sha and m.calls[-1] == "teardown"


def test_unregistered_and_missing_metrics_rejected(tmp_path):
    r, sha = _runner(FakeMcp(values={"success_rate": 1}), tmp_path)
    with pytest.raises(PermissionError):
        asyncio.run(r.run_policy(None, "home_v1", "0" * 64))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        asyncio.run(r.run_policy(None, "home_v1", sha))  # type: ignore[arg-type]


def test_nondeterministic_run_rejected_and_world_torn_down(tmp_path):
    m = FakeMcp(det=False)
    r, sha = _runner(m, tmp_path)
    with pytest.raises(RuntimeError):
        asyncio.run(r.run_policy(None, "home_v1", sha))  # type: ignore[arg-type]
    assert m.calls[-1] == "teardown"


def test_reality_gap_comes_from_a_real_reference(tmp_path):
    m = FakeMcp(values={"success_rate": 1, "reality_gap": 0, "safety_violation": 0, "x_m": 0.8})
    p = LinearPolicy.empty("home_v1", ("stop", "navigate"), 2)
    sc = PhysicsScenario("flat", "x.urdf", reference_x_m=1.0)
    r = GazeboPhysicsRunner(m, {}, {"home_v1": sc}, tmp_path)
    out = asyncio.run(r.run_policy(None, "home_v1", r.register(p)))  # type: ignore[arg-type]
    assert out["reality_gap"] == pytest.approx(0.2)


def test_pool_runs_candidates_in_parallel_and_returns_runners(tmp_path):
    from neml_brain.platform.physics import PooledPhysicsRunner

    live = peak = 0

    class SlowMcp(FakeMcp):
        async def call(self, server, tool, arguments=None, timeout_s=None):
            nonlocal live, peak
            if tool == "run_until":
                live += 1
                peak = max(peak, live)
                await asyncio.sleep(0.05)
                live -= 1
            return await super().call(server, tool, arguments, timeout_s)

    p = LinearPolicy.empty("home_v1", ("stop", "navigate"), 2)
    runners = [
        GazeboPhysicsRunner(SlowMcp(), {}, {"home_v1": PhysicsScenario("flat", "x")}, tmp_path)
        for _ in range(2)
    ]
    pool = PooledPhysicsRunner(runners)
    sha = pool.register(p)

    async def go():
        return await asyncio.gather(*(pool.run_policy(None, "home_v1", sha) for _ in range(4)))  # type: ignore[arg-type]

    assert len(asyncio.run(go())) == 4
    assert peak == 2  # never more than the pool size
