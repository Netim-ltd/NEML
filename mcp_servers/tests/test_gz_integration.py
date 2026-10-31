# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Real-Gazebo end to end (integration: skipped without `gz`).

    GZ_SIM_SYSTEM_PLUGIN_PATH=<dir with libNemlSystem.so> LIBGL_ALWAYS_SOFTWARE=1
    pytest -m integration mcp_servers/tests/test_gz_integration.py

The policy, not the test, drives the rover: "forward" wins the argmax tie, "stop"
wins it for the idle policy, so the two runs must differ in outcome.
"""

import asyncio
import hashlib
import os
import shutil
import tempfile
from pathlib import Path

import pytest
from neml_brain.platform.physics import GazeboPhysicsRunner, PhysicsScenario
from neml_brain.platform.policy import LinearPolicy

from mcp_servers._common import _coerce
from mcp_servers.neml_mcp_sim import server as sim

ROVER = str(sim.REPO_ROOT / "ros2_ws/src/neml_sim/models/test_rover.sdf")
ACTIONS_GO = ("forward", "stop")
ACTIONS_IDLE = ("stop", "forward")


async def run(policy: LinearPolicy, camera: bool) -> tuple[sim.RunMetrics, sim.RunResult, str]:
    path = Path(tempfile.mkdtemp()) / "policy.json"
    path.write_bytes(policy.to_bytes())
    world = await sim.load_world("flat", 7, "visual" if camera else "fast", timeout_s=120)
    robot = await sim.spawn_robot(
        ROVER, sim.Pose(z_m=0.02), "rover", timeout_s=30, policy_path=str(path)
    )
    assert robot.randomization["link_masses_kg"], "SDF masses were not read"
    res = await sim.run_until("sim_time_s>=6.0", timeout_s=6.0)
    frame = ""
    if camera:
        frame = (await sim.capture_camera(robot, "cam", timeout_s=60)).path
    m = await sim.get_metrics(robot, timeout_s=30)
    assert m.policy_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    await sim.teardown(world)
    return m, res, frame


class _InProcessMcp:
    """McpCaller that calls the sim tools directly, JSON-coerced like the HTTP server."""

    async def call(self, server, tool, arguments=None, timeout_s=None):  # type: ignore[no-untyped-def]
        from fastapi.encoders import jsonable_encoder

        fn = sim.TOOLS[tool]
        return jsonable_encoder(await fn(**_coerce(fn, dict(arguments or {}))))


async def physics_runner_case() -> None:
    runner = GazeboPhysicsRunner(
        _InProcessMcp(),
        {},
        {"rover": PhysicsScenario("flat", ROVER, seed=7, duration_s=6.0, spawn_z_m=0.02)},
        timeout_s=120,
    )
    go = LinearPolicy.empty("rover", ACTIONS_GO, 5)
    idle = LinearPolicy.empty("rover", ACTIONS_IDLE, 5)
    got = await runner.run_policy(None, "rover", runner.register(go))  # type: ignore[arg-type]
    none = await runner.run_policy(None, "rover", runner.register(idle))  # type: ignore[arg-type]
    print("PhysicsRunner go  :", got)
    print("PhysicsRunner idle:", none)
    assert got["success_rate"] == 1.0 and none["success_rate"] == 0.0
    assert got["model_sha256"] == runner.register(go)


async def main() -> None:
    sim.configure(runner=sim.GzRunner(), gpu_lock=_NoLock(), reset_state=True)
    go = LinearPolicy.empty("rover", ACTIONS_GO, 5)
    idle = LinearPolicy.empty("rover", ACTIONS_IDLE, 5)
    m_go, r_go, frame = await run(go, camera=True)
    print("go  :", m_go.values, r_go, "frame:", frame)
    m_idle, _, _ = await run(idle, camera=False)
    print("idle:", m_idle.values)
    assert m_go.values["success_rate"] == 1.0 and m_idle.values["success_rate"] == 0.0
    assert m_go.values["x_m"] > 1.0 and abs(m_idle.values["x_m"]) < 0.05
    assert Path(frame).stat().st_size > 1000, "camera frame is empty"
    await physics_runner_case()
    print("E2E OK")


class _NoLock:
    async def acquire(self, *_: object, **__: object) -> None: ...
    async def release(self, *_: object, **__: object) -> None: ...


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("gz") is None, reason="needs Gazebo Harmonic + libNemlSystem.so")
def test_policy_drives_rover_in_real_gazebo() -> None:
    asyncio.run(main())


@pytest.mark.integration
@pytest.mark.skipif(
    shutil.which("gz") is None or not os.environ.get("NEML_QUAD_URDF"),
    reason="needs Gazebo and NEML_QUAD_URDF=<xacro-expanded quadruped_v2.urdf>",
)
def test_quadruped_urdf_spawns_and_steps() -> None:
    async def go() -> None:
        sim.configure(runner=sim.GzRunner(), gpu_lock=_NoLock(), reset_state=True)
        world = await sim.load_world("flat", 3, "fast", timeout_s=120)
        robot = await sim.spawn_robot(
            os.environ["NEML_QUAD_URDF"], sim.Pose(z_m=0.4), "quad", timeout_s=60
        )
        assert len(robot.randomization["link_masses_kg"]) >= 16
        assert (await sim.step(1.0, timeout_s=120)).steps == 1000
        await sim.teardown(world)

    asyncio.run(go())
