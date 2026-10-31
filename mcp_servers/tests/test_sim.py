# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for neml-mcp-sim (SPEC 6.3).

The invariants that make a sim run usable by evolution:
  * same seed + same sim_version -> same metrics within 2% (SPEC 11.2),
  * the `visual` profile holds the GPU mutex for its whole life (SPEC 4.5),
  * SI units only, no payload where the contract promises a path reference.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import pytest

from mcp_servers.neml_mcp_sim import server


def call[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


class FakeRunner:
    """Scripted Gazebo. `metrics` pops one reply per call so drift is testable."""

    def __init__(self, metrics: list[dict[str, float]] | None = None) -> None:
        self.ops: list[str] = []
        self.payloads: list[dict[str, Any]] = []
        self.metrics = list(metrics or [])
        self.replies: dict[str, dict[str, Any]] = {"version": {"gz_version": "8.9.0"}}
        self.fail_on: str = ""

    async def call(self, op: str, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        self.ops.append(op)
        self.payloads.append(payload)
        if op == self.fail_on:
            raise RuntimeError(f"scripted failure on {op}")
        if op == "metrics":
            return {"values": self.metrics.pop(0) if self.metrics else {}}
        return self.replies.get(op, {})


class FakeGpuLock:
    def __init__(self) -> None:
        self.held: list[str] = []
        self.log: list[str] = []

    async def acquire(self, consumer: str, timeout_s: float = 0.0) -> None:
        self.held.append(consumer)
        self.log.append(f"acquire:{consumer}")

    async def release(self, consumer: str) -> None:
        self.held.remove(consumer)
        self.log.append(f"release:{consumer}")


@pytest.fixture
def lab(tmp_path: Path) -> tuple[FakeRunner, FakeGpuLock, Path]:
    worlds = tmp_path / "worlds"
    worlds.mkdir()
    (worlds / "flat.sdf").write_text("<sdf/>", encoding="utf-8")
    urdf = tmp_path / "robot.urdf"
    urdf.write_text("<robot name='r'/>", encoding="utf-8")
    runner, lock = FakeRunner(), FakeGpuLock()
    server.configure(reset_state=True, runner=runner, gpu_lock=lock, world_dir=worlds)
    return runner, lock, urdf


def load(profile: str = "fast") -> server.WorldHandle:
    return call(server.load_world("flat", 42, profile))  # type: ignore[arg-type]


def spawn(urdf: Path) -> server.RobotHandle:
    return call(server.spawn_robot(str(urdf), server.Pose(), "r1"))


# --- SPEC 4.5: the GPU mutex ------------------------------------------------


def test_visual_profile_holds_the_gpu_mutex_until_teardown(
    lab: tuple[FakeRunner, FakeGpuLock, Path],
) -> None:
    _, lock, _urdf = lab
    world = load("visual")
    assert lock.held == ["gazebo"]
    call(server.teardown(world))
    assert lock.held == []
    assert lock.log == ["acquire:gazebo", "release:gazebo"]


def test_headless_profile_leaves_the_gpu_to_vllm(
    lab: tuple[FakeRunner, FakeGpuLock, Path],
) -> None:
    _, lock, _urdf = lab
    world = load("fast")
    call(server.teardown(world))
    assert lock.log == []


def test_unknown_profile_is_refused(lab: tuple[FakeRunner, FakeGpuLock, Path]) -> None:
    with pytest.raises(server.SimProfileError):
        call(server.load_world("flat", 1, "pretty"))  # type: ignore[arg-type]


def test_missing_world_file_is_refused(lab: tuple[FakeRunner, FakeGpuLock, Path]) -> None:
    with pytest.raises(server.SimStateError):
        call(server.load_world("no_such_world", 1, "fast"))


# --- SPEC 11.2: determinism -------------------------------------------------


def test_same_seed_and_version_reproduce_within_tolerance(
    lab: tuple[FakeRunner, FakeGpuLock, Path],
) -> None:
    runner, _lock, urdf = lab
    runner.metrics = [{"distance_m": 10.0}, {"distance_m": 10.1}]  # 1% drift, inside 2%
    load()
    robot = spawn(urdf)
    first = call(server.get_metrics(robot))
    second = call(server.get_metrics(robot))
    assert first.deterministic and second.deterministic
    assert first.sim_version == second.sim_version
    assert first.seed == 42


def test_drift_beyond_two_percent_is_flagged(
    lab: tuple[FakeRunner, FakeGpuLock, Path],
) -> None:
    runner, _lock, urdf = lab
    runner.metrics = [{"distance_m": 10.0}, {"distance_m": 10.5}]  # 5% drift
    load()
    robot = spawn(urdf)
    call(server.get_metrics(robot))
    assert call(server.get_metrics(robot)).deterministic is False


def test_sim_version_tracks_the_world_and_the_urdf(
    lab: tuple[FakeRunner, FakeGpuLock, Path], tmp_path: Path
) -> None:
    _runner, _lock, urdf = lab
    world = load()
    robot = spawn(urdf)
    changed = tmp_path / "robot2.urdf"
    changed.write_text("<robot name='r2'/>", encoding="utf-8")
    other = call(server.spawn_robot(str(changed), server.Pose(), "r2"))
    assert server.sim_version(world, robot) != server.sim_version(world, other)


# --- SPEC 6.3: SI units, path references, no unbounded call -----------------


def test_sensor_without_a_declared_si_unit_is_refused(
    lab: tuple[FakeRunner, FakeGpuLock, Path],
) -> None:
    _runner, _lock, urdf = lab
    load()
    robot = spawn(urdf)
    with pytest.raises(server.SimUnitError):
        call(server.read_sensor(robot, "vibes"))
    assert call(server.read_sensor(robot, "imu")).unit == "rad/s"


def test_camera_needs_the_visual_profile(lab: tuple[FakeRunner, FakeGpuLock, Path]) -> None:
    _runner, _lock, urdf = lab
    load("fast")
    robot = spawn(urdf)
    with pytest.raises(server.SimProfileError):
        call(server.capture_camera(robot, "front"))


def test_camera_payload_instead_of_a_path_is_refused(
    lab: tuple[FakeRunner, FakeGpuLock, Path],
) -> None:
    runner, _lock, urdf = lab
    runner.replies["camera"] = {"data": "<bytes>"}
    load("visual")
    robot = spawn(urdf)
    with pytest.raises(server.SimUnitError):
        call(server.capture_camera(robot, "front"))


def test_run_until_requires_a_positive_timeout(
    lab: tuple[FakeRunner, FakeGpuLock, Path],
) -> None:
    load()
    with pytest.raises(server.SimStateError):
        call(server.run_until("fallen", 0.0))


def test_calls_before_load_world_are_refused(
    lab: tuple[FakeRunner, FakeGpuLock, Path],
) -> None:
    with pytest.raises(server.SimStateError):
        call(server.step(0.1))


def test_teardown_refuses_a_stale_handle(lab: tuple[FakeRunner, FakeGpuLock, Path]) -> None:
    load()
    stale = server.WorldHandle("other", 1, "fast", "x", "8.9.0", "run")
    with pytest.raises(server.SimStateError):
        call(server.teardown(stale))


def test_unknown_robot_namespace_is_refused(lab: tuple[FakeRunner, FakeGpuLock, Path]) -> None:
    load()
    ghost = server.RobotHandle("ghost", "none.urdf", "0" * 64)
    with pytest.raises(server.SimStateError):
        call(server.get_contacts(ghost))


# --- SPEC 6.3: the contract itself ------------------------------------------

# The twelve names SPEC 6.3 lists, and nothing else.
CONTRACT = {
    "set_seed",
    "load_world",
    "spawn_robot",
    "step",
    "run_until",
    "read_sensor",
    "capture_camera",
    "get_contacts",
    "apply_wrench",
    "get_metrics",
    "reset",
    "teardown",
}


def test_the_served_tools_are_exactly_the_spec_contract() -> None:
    """T-036's harness and the rule-3 filter are module functions, not tools.

    They take no `timeout_s` / are not called over MCP, and SPEC 6.3 names
    twelve functions. Publishing a thirteenth is how a contract stops being one.
    """
    assert set(server.TOOLS) == CONTRACT
    assert callable(server.determinism_check) and callable(server.evolution_input)


def test_no_tool_can_block_forever() -> None:
    """SPEC 6.3: every call that reaches the simulator carries a timeout."""
    for name, fn in server.TOOLS.items():
        if inspect.iscoroutinefunction(fn):
            assert "timeout_s" in inspect.signature(fn).parameters, name


def test_every_failure_is_one_typed_family() -> None:
    for error in (
        server.SimTimeoutError,
        server.SimStateError,
        server.SimProfileError,
        server.SimUnitError,
    ):
        assert issubclass(error, server.SimError)


def test_a_runner_blow_up_arrives_as_a_sim_error(lab: tuple[FakeRunner, FakeGpuLock, Path]) -> None:
    runner, _lock, _urdf = lab
    load()
    runner.fail_on = "step"
    with pytest.raises(server.SimError):
        call(server.step(0.1))


def test_a_runner_timeout_arrives_as_a_sim_timeout(
    lab: tuple[FakeRunner, FakeGpuLock, Path],
) -> None:
    class Stalled(FakeRunner):
        async def call(self, op: str, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
            if op == "step":
                raise TimeoutError("gz never answered")
            return await super().call(op, payload, timeout_s)

    server.configure(runner=Stalled())
    load()
    with pytest.raises(server.SimTimeoutError):
        call(server.step(0.1))


def test_camera_hands_back_a_path_reference(lab: tuple[FakeRunner, FakeGpuLock, Path]) -> None:
    runner, _lock, urdf = lab
    runner.replies["camera"] = {"path": "/srv/neml/work/sim/front_0001.png", "width_px": 424}
    load("visual")
    image = call(server.capture_camera(spawn(urdf), "front"))
    assert image.path.endswith(".png") and image.width_px == 424
    assert not hasattr(image, "data")


def test_units_are_si_for_every_readable_sensor() -> None:
    assert set(server.SENSOR_UNITS.values()) == {"rad/s", "rad", "N", "m", "A", "V", "K"}


def test_a_sensor_payload_is_refused_like_a_camera_payload(
    lab: tuple[FakeRunner, FakeGpuLock, Path],
) -> None:
    """SPEC 6.3: point clouds return a reference. read_sensor is the only door
    left once capture_camera is shut, so it is shut the same way."""
    runner, _lock, urdf = lab
    load()
    robot = spawn(urdf)
    for payload in ({"points": [[0.0, 0.0, 0.0]]}, {"data": "<bytes>"}):
        runner.replies["sensor"] = payload
        with pytest.raises(server.SimUnitError):
            call(server.read_sensor(robot, "lidar"))


# --- SPEC 11.2 rule 1: the seed ---------------------------------------------


def test_set_seed_does_not_invent_a_gazebo_service(
    lab: tuple[FakeRunner, FakeGpuLock, Path],
) -> None:
    """Gazebo has no seed service; the seed rides load_world and the SPEC 11.4
    sampling. A call to the runner here would be a guaranteed failure on the
    lab host and a silent pass against any double."""
    runner, _lock, _urdf = lab
    call(server.set_seed(99))
    assert runner.ops == []
    assert server._S.seed == 99


def test_reseeding_a_live_world_is_refused(lab: tuple[FakeRunner, FakeGpuLock, Path]) -> None:
    """Two seeds in one run is the one split SPEC 11.2 rule 3 cannot see: the
    metrics would differ and the sim_version would not."""
    world = load()
    with pytest.raises(server.SimStateError):
        call(server.set_seed(99))
    call(server.teardown(world))
    call(server.set_seed(99))
    assert server._S.seed == 99


def test_a_failed_visual_load_gives_the_gpu_back(
    lab: tuple[FakeRunner, FakeGpuLock, Path],
) -> None:
    """SPEC 4.5: the world never loaded, so no handle exists and teardown can
    never run. Holding the mutex here keeps vLLM stopped indefinitely."""
    runner, lock, _urdf = lab
    runner.fail_on = "load_world"
    with pytest.raises(server.SimError):
        load("visual")
    assert lock.held == []
    assert lock.log == ["acquire:gazebo", "release:gazebo"]
    assert server._S.gpu_held is False


def test_physics_changes_the_run_record_and_the_sim_version(
    lab: tuple[FakeRunner, FakeGpuLock, Path],
) -> None:
    _runner, _lock, urdf = lab
    load()
    nominal = spawn(urdf)
    nominal_version = server.sim_version(server._world(), nominal)
    call(server.teardown(server._world()))
    physics = {
        "friction": 1.0,
        "joint_damping": 0.5,
        "motor_gain": 1.2,
        "body_inertia_correction": 1.1,
        "comms_latency_s": 0.02,
    }
    world = call(server.load_world("flat", 42, "fast", physics=physics))
    robot = spawn(urdf)
    assert robot.randomization["joint_damping"] == 0.5
    assert server.sim_version(world, robot) != nominal_version
