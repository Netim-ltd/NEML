# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""neml-mcp-sim - Gazebo Harmonic MCP server, port 9101 (SPEC 6.2 #10, SPEC 6.3).

Rules enforced here, not in a prompt:
  * SI units only - sensor names map to a fixed SI unit table.
  * No unbounded blocking call - every entry point takes `timeout_s`.
  * Images and point clouds come back as a path reference, never a payload.
  * Same seed + same sim_version -> same metrics within 2% (SPEC 11.2), else the
    run is flagged deterministic=False and evolution must not use it.
  * The six SPEC 11.4 parameters are randomised +/-15% from the run seed and
    recorded with the run, so a run replays exactly.
  * The `visual` profile takes the GPU mutex before it runs (SPEC 4.5).
  * Nothing here reads a clock (SPEC 11.2 rule 4); only sim time exists.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import shutil
import tempfile
import uuid
import xml.etree.ElementTree as ET  # nosec B405 - URDFs are generated in-tree, never fetched
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from mcp_servers._common import make_app, run_cli
from mcp_servers.neml_mcp_sim.determinism import (
    DEFAULT_RUNS,
    TOLERANCE,
    DeterminismReport,
    compare_runs,
    usable_runs,
    within_tolerance,
)

PORT = 9101
VERSION = "1.0.0"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TIMEOUT_S = 60.0
PROFILES = ("fast", "lidar", "visual")
# SPEC 11.4: the motor torque constant is a datasheet number the genome owns, so
# the sim randomises a multiplier around it. 1.0 means "datasheet, unscaled".
NOMINAL_TORQUE_SCALE = 1.0

# SPEC 6.3: SI everywhere. A sensor that is not in this table cannot be read.
SENSOR_UNITS = {
    "imu": "rad/s",
    "encoder": "rad",
    "contact": "N",
    "lidar": "m",
    "current": "A",
    "voltage": "V",
    "temperature": "K",
}


class SimError(RuntimeError):
    """Base typed error for every sim entry point."""


class SimTimeoutError(SimError):
    """The simulator did not answer inside the caller's timeout."""


class SimStateError(SimError):
    """No world loaded, unknown robot, or handle does not match the live world."""


class SimProfileError(SimError):
    """Operation is not available in the loaded profile (SPEC 4.5)."""


class SimUnitError(SimError):
    """Sensor is not in the SI unit table, or a payload came back instead of a path."""


@dataclass
class Vec3:
    x: float
    y: float
    z: float


@dataclass
class Pose:
    """Metres and radians. SI only."""

    x_m: float = 0.0
    y_m: float = 0.0
    z_m: float = 0.0
    roll_rad: float = 0.0
    pitch_rad: float = 0.0
    yaw_rad: float = 0.0


@dataclass
class WorldHandle:
    world_id: str
    seed: int
    profile: str
    world_sha256: str
    gz_version: str
    run_dir: str
    # SPEC 11.3 calibrated physics, or None for the nominals. Applied at spawn
    # and folded into sim_version: two runs with different physics are not
    # comparable (SPEC 11.2).
    physics: dict[str, float] | None = None


@dataclass
class RobotHandle:
    ns: str
    urdf_path: str
    urdf_sha256: str
    # SPEC 11.4 / T-037: the six randomised parameters actually applied to this
    # robot. Evidence for the run record, not debug output - replaying the run
    # means replaying these numbers.
    randomization: dict[str, Any] = field(default_factory=dict)


@dataclass
class SimTime:
    sim_time_s: float
    steps: int


@dataclass
class RunResult:
    condition: str
    satisfied: bool
    sim_time_s: float
    timed_out: bool


@dataclass
class SensorReading:
    sensor: str
    unit: str
    values: list[float]
    sim_time_s: float


@dataclass
class ImageRef:
    """A path, never pixels (SPEC 6.3)."""

    path: str
    width_px: int
    height_px: int
    encoding: str


@dataclass
class Contact:
    link: str
    other_link: str
    force_N: Vec3
    position_m: Vec3


@dataclass
class RunMetrics:
    seed: int
    sim_version: str
    values: dict[str, float]
    deterministic: bool
    randomization: dict[str, Any] = field(default_factory=dict)
    # sha256 of the policy file the simulator actually executed; "" when none was loaded.
    policy_sha256: str = ""


class SimRunner(Protocol):
    """The only seam that touches Gazebo. Injected so the server is testable."""

    async def call(self, op: str, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]: ...


# Gazebo services. `gz sim` hosts the world; everything else is a service or a
# topic echo. ponytail: the request encodings below are CLI-shaped and must be
# re-checked against a live Harmonic install in T-034 - Gazebo is not installed
# on the authoring host, so they are unverified here.
_SERVICES = {
    "spawn": ("/world/{world}/create", "gz.msgs.EntityFactory"),
    "step": ("/world/{world}/control", "gz.msgs.WorldControl"),
    "reset": ("/world/{world}/control", "gz.msgs.WorldControl"),
    "wrench": ("/world/{world}/wrench", "gz.msgs.EntityWrench"),
    "policy": ("/world/{world}/neml/policy", "gz.msgs.StringMsg"),
    "randomize": ("/world/{world}/neml/randomize", "gz.msgs.StringMsg"),
    "run_until": ("/world/{world}/neml/run_until", "gz.msgs.StringMsg"),
    "metrics": ("/world/{world}/neml/metrics", "gz.msgs.StringMsg"),
    "camera": ("/world/{world}/neml/capture", "gz.msgs.StringMsg"),
    "teardown": ("/world/{world}/neml/shutdown", "gz.msgs.StringMsg"),
}
# Gazebo topic templates, copied from config/gz_bridge.yaml (SPEC 11.1) with its
# <ns>/<world> placeholders rewritten as format fields. The copy is deliberate -
# the server does not parse the bridge config at runtime - and
# mcp_servers/tests/test_sim_bridge.py fails the moment the two drift apart.
# Keys are SENSOR_UNITS names; a sensor with no bridge entry cannot be read.
_SENSOR_TOPICS = {
    "imu": "/world/{world}/model/{ns}/link/base_link/sensor/imu/imu",
    "encoder": "/world/{world}/model/{ns}/joint_state",
    "contact": "/world/{world}/model/{ns}/link/foot/sensor/contact/contact",
    "lidar": "/world/{world}/model/{ns}/link/lidar_link/sensor/lidar/scan",
}
_ECHO_OPS = ("sensor", "contacts")  # `gz topic -e`, one message, no service call


class GzRunner:
    """Real driver: a persistent paused `gz sim -s` plus `gz service` / `gz topic`.

    The world is started paused and stepped only through WorldControl, so sim
    time moves exactly when the server says (SPEC 11.2). `NemlSystem` (neml_sim
    package) answers the /world/<w>/neml/* services; put the folder holding
    libNemlSystem.so on GZ_SIM_SYSTEM_PLUGIN_PATH.
    """

    STEP_S = 0.001  # worlds fix max_step_size at 1 ms (SPEC 11.1)
    CHUNK_STEPS = 250  # run_until re-checks its condition every 0.25 s of sim time

    def __init__(self, gz_bin: str = "gz", partition: str | None = None) -> None:
        """`partition` isolates this runner's Gazebo transport from other sim servers."""
        self.gz_bin = gz_bin
        self.partition = partition
        self._proc: asyncio.subprocess.Process | None = None

    def _env(self, argv: list[str]) -> list[str]:
        return ["env", f"GZ_PARTITION={self.partition}", *argv] if self.partition else argv

    async def _service(
        self, service: str, reqtype: str, reptype: str, req: str, timeout_s: float
    ) -> str:
        argv = [
            self.gz_bin, "service", "-s", service, "--reqtype", reqtype,
            "--reptype", reptype, "--timeout", str(int(timeout_s * 1000)), "--req", req,
        ]  # fmt: skip
        return (await run_cli(self._env(argv), timeout_s + 5)).strip()

    async def _neml(self, world: str, name: str, req: dict[str, Any], timeout_s: float) -> Any:
        """neml/* services take a StringMsg whose `data` is the JSON request."""
        out = await self._service(
            f"/world/{world}/neml/{name}",
            "gz.msgs.StringMsg",
            "gz.msgs.StringMsg",
            f"data: {json.dumps(json.dumps(req))}",
            timeout_s,
        )
        # reply is protobuf text `data: "<json>"`; the quoted string is JSON-escaped.
        body = out.removeprefix("data:").strip()
        if not body.startswith('"'):
            raise RuntimeError(f"neml/{name} returned {out!r}")
        reply = dict(json.loads(json.loads(body)))
        if "error" in reply:
            raise RuntimeError(f"neml/{name}: {reply['error']}")
        return reply

    async def _advance(self, world: str, steps: int, timeout_s: float) -> float:
        """multi_step N, then wait until the plugin has seen N more iterations."""
        before = float((await self._neml(world, "run_until", {}, timeout_s))["sim_time_s"])
        await self._service(
            f"/world/{world}/control",
            "gz.msgs.WorldControl",
            "gz.msgs.Boolean",
            f"multi_step: {steps} pause: true",
            timeout_s,
        )
        target = before + steps * self.STEP_S - self.STEP_S / 2
        deadline = asyncio.get_running_loop().time() + timeout_s
        while True:
            now = float((await self._neml(world, "run_until", {}, timeout_s))["sim_time_s"])
            if now >= target:
                return now
            if asyncio.get_running_loop().time() > deadline:
                raise TimeoutError(f"world {world} did not advance {steps} steps")
            await asyncio.sleep(0.02)

    async def call(self, op: str, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        if op == "version":
            return {
                "gz_version": (await run_cli([self.gz_bin, "sim", "--versions"], timeout_s)).strip()
            }
        if op == "load_world":
            return await self._load_world(payload["world_path"], timeout_s)
        if op in _ECHO_OPS:
            argv = [
                self.gz_bin, "topic", "-e", "-t", payload["topic"], "-n", "1", "--json-output",
            ]  # fmt: skip
            return dict(json.loads(await run_cli(self._env(argv), timeout_s) or "{}"))
        world = payload.get("world", "")
        req = payload.get("req", {})
        if op == "step":
            steps = int(req["multi_step"])
            return {"sim_time_s": await self._advance(world, steps, timeout_s), "steps": steps}
        if op == "run_until":
            return await self._run_until(world, req, timeout_s)
        if op == "spawn":
            await self._service(
                f"/world/{world}/create",
                "gz.msgs.EntityFactory",
                "gz.msgs.Boolean",
                _entity_factory({**req, "sdf_filename": _with_friction(req)}),
                timeout_s,
            )
            return {}
        if op == "reset":
            await self._service(
                f"/world/{world}/control",
                "gz.msgs.WorldControl",
                "gz.msgs.Boolean",
                "reset: {all: true}",
                timeout_s,
            )
            return {}
        if op == "teardown":
            await self._stop()
            return {}
        service, reqtype = _SERVICES[op]
        if op == "camera":
            return await self._capture(world, req, timeout_s)
        if "/neml/" in service:
            return dict(await self._neml(world, service.rsplit("/", 1)[1], req, timeout_s))
        out = await self._service(
            service.format(**payload), reqtype, "gz.msgs.Boolean", json.dumps(req), timeout_s
        )
        return {"raw": out}

    async def _capture(self, world: str, req: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        """The plugin subscribes on first use; a paused world needs a few steps to render."""
        for _ in range(3):
            try:
                return dict(await self._neml(world, "capture", req, timeout_s))
            except RuntimeError as exc:
                if "no_frame" not in str(exc):
                    raise
                await self._advance(world, 100, timeout_s)
        raise RuntimeError("camera produced no frame")

    async def _load_world(self, world_path: str, timeout_s: float) -> dict[str, Any]:
        await self._stop()
        world = Path(world_path).stem  # every worlds/*.sdf names its world after its file
        # No -r: the world starts paused and moves only on WorldControl.
        self._proc = await asyncio.create_subprocess_exec(
            *self._env([self.gz_bin, "sim", "-s", "--headless-rendering", world_path]),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )  # fmt: skip
        deadline = asyncio.get_running_loop().time() + timeout_s
        while True:
            if self._proc.returncode is not None:
                raise RuntimeError(f"gz sim exited {self._proc.returncode} while loading")
            listing = await run_cli(self._env([self.gz_bin, "service", "-l"]), 10)
            if f"/world/{world}/neml/metrics" in listing:
                return {}
            if asyncio.get_running_loop().time() > deadline:
                await self._stop()
                raise TimeoutError(f"world {world} did not come up (is NemlSystem on the path?)")
            await asyncio.sleep(0.5)

    async def _run_until(self, world: str, req: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        limit = float(req["timeout_s"])
        while True:
            state = await self._neml(world, "run_until", req, timeout_s)
            if state["satisfied"]:
                return {**state, "timed_out": False}
            remaining = limit - float(state["sim_time_s"])
            if remaining <= 0:
                return {**state, "timed_out": True}
            steps = min(self.CHUNK_STEPS, max(1, int(remaining / self.STEP_S)))
            cond = str(req.get("condition", ""))
            if cond.startswith("sim_time_s>="):
                # a pure time condition needs no re-check: jump straight to it
                left = min(
                    remaining, float(cond.removeprefix("sim_time_s>=")) - float(state["sim_time_s"])
                )
                steps = min(5000, max(1, round(left / self.STEP_S)))
            await self._advance(world, steps, timeout_s)

    async def _stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None or proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), 10)
        except TimeoutError:
            proc.kill()
            await proc.wait()


NOMINAL_FRICTION = 0.7  # SPEC 11.4 nominal; the world files use the same mu


def _with_friction(req: dict[str, Any]) -> str:
    """Path of the SDF to spawn: a copy with every wheel/foot mu scaled to the sampled friction.

    The ratio is friction / NOMINAL_FRICTION, so a model authored at any mu moves
    by the same +-15% as the nominal surface. A URDF (or a model with no mu)
    is spawned unchanged. ponytail: copy lands in the temp dir, one per spawn (never cleaned).
    """
    path = str(req["sdf_filename"])
    friction = req.get("friction")
    if friction is None or not path.endswith(".sdf"):
        return path
    tree = ET.parse(path)  # noqa: S314  # nosec B314 - local, in-tree model
    scale = float(friction) / NOMINAL_FRICTION
    changed = False
    for tag in ("mu", "mu2"):
        for el in tree.getroot().iter(tag):
            if el.text and float(el.text) > 0:
                el.text = repr(float(el.text) * scale)
                changed = True
    if not changed:
        return path
    # The copy lives elsewhere, so relative mesh / include paths must point home.
    for uri in tree.getroot().iter("uri"):
        text = (uri.text or "").strip()
        if text and "://" not in text and not Path(text).is_absolute():
            uri.text = str((Path(path).parent / text).resolve())
    out = Path(tempfile.mkdtemp(prefix="neml_sdf_")) / Path(path).name
    tree.write(out, encoding="utf-8", xml_declaration=True)
    return str(out)


def _entity_factory(req: dict[str, Any]) -> str:
    """gz.msgs.EntityFactory text for /world/<w>/create (pose in m / rad)."""
    pose = req["pose"]
    cr, sr = math.cos(pose["roll_rad"] / 2), math.sin(pose["roll_rad"] / 2)
    cp, sp = math.cos(pose["pitch_rad"] / 2), math.sin(pose["pitch_rad"] / 2)
    cy, sy = math.cos(pose["yaw_rad"] / 2), math.sin(pose["yaw_rad"] / 2)
    q = (
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
        cr * cp * cy + sr * sp * sy,
    )
    return (
        f"sdf_filename: {json.dumps(req['sdf_filename'])} name: {json.dumps(req['name'])} "
        f"pose: {{position: {{x: {pose['x_m']} y: {pose['y_m']} z: {pose['z_m']}}} "
        f"orientation: {{x: {q[0]} y: {q[1]} z: {q[2]} w: {q[3]}}}}}"
    )


@dataclass
class _State:
    runner: SimRunner = field(default_factory=GzRunner)
    gpu_lock: Any = None
    world_dir: Path = field(
        default_factory=lambda: REPO_ROOT / "ros2_ws" / "src" / "neml_sim" / "worlds"
    )
    seed: int | None = None
    world: WorldHandle | None = None
    robots: dict[str, RobotHandle] = field(default_factory=dict)
    baselines: dict[str, dict[str, float]] = field(default_factory=dict)
    gpu_held: bool = False


_S = _State()


def configure(
    runner: SimRunner | None = None,
    gpu_lock: Any = None,
    world_dir: Path | None = None,
    reset_state: bool = False,
) -> None:
    """Injection point for tests and for the lab process wiring."""
    global _S
    if reset_state:
        _S = _State()
    if runner is not None:
        _S.runner = runner
    if gpu_lock is not None:
        _S.gpu_lock = gpu_lock
    if world_dir is not None:
        _S.world_dir = Path(world_dir)


def _lock() -> Any:
    if _S.gpu_lock is None:
        # Imported lazily: the lock lives in the brain package (SPEC 4.5) and the
        # sim server must still import cleanly when it is not installed.
        from neml_brain.runtime.gpu_lock import GpuLock

        _S.gpu_lock = GpuLock()
    return _S.gpu_lock


def _link_masses_kg(urdf_path: str) -> dict[str, float]:
    """The CAD masses SPEC 11.4 randomises, read from the URDF that is spawned.

    A URDF with no inertial blocks (a test stub, a sensor-only description)
    yields an empty map rather than an error: the other five parameters are
    still randomised and recorded.
    """
    try:
        root = ET.parse(urdf_path).getroot()  # noqa: S314  # nosec B314 - local, generated URDF
    except ET.ParseError as exc:
        raise SimStateError(f"{urdf_path} is not parseable XML: {exc}") from exc
    masses: dict[str, float] = {}
    for link in root.iter("link"):
        mass = link.find("inertial/mass")
        name = link.get("name")
        if mass is None or name is None:
            continue
        # URDF: <mass value="..."/>; SDF: <mass>...</mass>
        text = mass.get("value") or (mass.text or "").strip()
        if text:
            masses[name] = float(str(text))
    return masses


def _randomize(
    seed: int, urdf_path: str, torque_scale: float, physics: dict[str, float] | None = None
) -> dict[str, Any]:
    """SPEC 11.4 sampling. Imported lazily: same reason as the GPU lock.

    SPEC 11.3 physics moves the nominals the +/-15% is drawn around, so the
    calibration and the randomisation stay one record: friction, latency and
    motor gain replace their nominals, body_inertia_correction scales every
    link mass, joint_damping rides along as an extra request field.
    """
    from neml_brain.evolution.randomization import NOMINALS, randomize

    masses = _link_masses_kg(urdf_path)
    if not physics:
        return randomize(seed, link_masses_kg=masses, motor_torque_constant=torque_scale)
    nominals = {
        **NOMINALS,
        "surface_friction": physics["friction"],
        "control_latency_s": physics["comms_latency_s"],
    }
    record = randomize(
        seed,
        link_masses_kg={k: v * physics["body_inertia_correction"] for k, v in masses.items()},
        motor_torque_constant=torque_scale * physics["motor_gain"],
        nominals=nominals,
    )
    record["joint_damping"] = physics["joint_damping"]
    return record


def _sha256_file(path: str) -> str:
    file = Path(path)
    if not file.is_file():
        raise SimStateError(f"file not found: {path}")
    return hashlib.sha256(file.read_bytes()).hexdigest()


def _world() -> WorldHandle:
    if _S.world is None:
        raise SimStateError("no world loaded; call load_world first")
    return _S.world


def _topic(sensor: str, world: str, ns: str) -> str:
    """The gz topic config/gz_bridge.yaml maps for this sensor (SPEC 11.1)."""
    try:
        return _SENSOR_TOPICS[sensor].format(world=world, ns=ns)
    except KeyError as exc:
        raise SimStateError(
            f"sensor '{sensor}' has no entry in config/gz_bridge.yaml; it is not simulated"
        ) from exc


def _robot(ns: str) -> RobotHandle:
    try:
        return _S.robots[ns]
    except KeyError as exc:
        raise SimStateError(f"unknown robot namespace '{ns}'") from exc


async def _run(op: str, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    try:
        return await _S.runner.call(op, payload, timeout_s)
    except SimError:
        raise
    except TimeoutError as exc:
        raise SimTimeoutError(f"{op} exceeded {timeout_s}s") from exc
    except Exception as exc:
        if type(exc).__name__ == "CliTimeout":
            raise SimTimeoutError(str(exc)) from exc
        raise SimError(f"{op} failed: {type(exc).__name__}: {exc}") from exc


# --- SPEC 6.3 interface contract -------------------------------------------


async def set_seed(seed: int, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
    """Fix the run seed; every randomisation derives from it (SPEC 11.2 rule 1).

    Gazebo has no seed service. The seed reaches the simulator through
    `load_world` and through the SPEC 11.4 sampling in `spawn_robot`, and both
    read it from here, so this call only fixes the number. `timeout_s` is part
    of the SPEC 6.3 signature and unused: nothing leaves the process.

    Re-seeding under a live world is refused. It would split one run across two
    seeds, which is exactly the state SPEC 11.2 rule 3 cannot detect - the
    metrics would differ and the sim_version would not.
    """
    del timeout_s
    if _S.world is not None:
        raise SimStateError("the seed is fixed for the life of a world; teardown first")
    _S.seed = int(seed)


async def load_world(
    world_id: str,
    seed: int,
    profile: Literal["fast", "lidar", "visual"],
    timeout_s: float = DEFAULT_TIMEOUT_S,
    physics: dict[str, float] | None = None,
) -> WorldHandle:
    """Load a world headless. `visual` takes the GPU mutex and stops vLLM.

    `physics` carries the five SPEC 11.3 calibration parameters; spawn_robot
    applies them to the robot it creates.
    """
    if profile not in PROFILES:
        raise SimProfileError(f"profile must be one of {PROFILES}, got '{profile}'")
    world_path = str(_S.world_dir / f"{world_id}.sdf")
    if not Path(world_path).exists():  # worlds the lab designed for itself (validated before they were written)
        extra = Path(os.environ.get("NEML_ARTIFACT_DIR", "/srv/neml/artifacts")) / "worlds" / f"{world_id}.sdf"
        if extra.exists() and "/" not in world_id and ".." not in world_id:
            world_path = str(extra)
    world_sha = _sha256_file(world_path)
    if profile == "visual":
        # SPEC 4.5: 3 GB does not hold vLLM and a rendering Gazebo at once.
        await _lock().acquire("gazebo", timeout_s=timeout_s)
        _S.gpu_held = True
    try:
        version = await _run("version", {}, timeout_s)
        await _run(
            "load_world",
            {"world_path": world_path, "seed": int(seed), "profile": profile},
            timeout_s,
        )
    except BaseException:
        # A world that never loaded has no handle, so teardown can never be
        # called and the mutex would be held until the daemon restarts - vLLM
        # stays stopped for a failure that lasted a second (SPEC 4.5).
        if _S.gpu_held:
            _S.gpu_held = False
            await _lock().release("gazebo")
        raise
    _S.seed = int(seed)
    _S.robots.clear()
    _S.world = WorldHandle(
        world_id=world_id,
        seed=int(seed),
        profile=profile,
        world_sha256=world_sha,
        gz_version=str(version.get("gz_version", "unknown")),
        run_dir=f"/srv/neml/work/sim/{world_id}_{seed}",
        physics=dict(physics) if physics else None,
    )
    return _S.world


async def spawn_robot(
    urdf_path: str,
    pose: Pose,
    ns: str,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    motor_torque_constant: float = NOMINAL_TORQUE_SCALE,
    policy_path: str | None = None,
) -> RobotHandle:
    """Spawn a URDF into the live world at an SI pose (m, rad).

    T-037: the six SPEC 11.4 parameters are sampled here - the last point before
    physics runs and the first point where the link masses are known - from the
    world seed, applied to the sim, and kept on the handle as the run record.
    """
    world = _world()
    urdf_sha = _sha256_file(urdf_path)
    randomization = _randomize(world.seed, urdf_path, motor_torque_constant, world.physics)
    await _run(
        "spawn",
        {
            "world": world.world_id,
            "req": {
                "sdf_filename": urdf_path,
                "name": ns,
                "pose": vars(pose),
                "friction": randomization["surface_friction"],
            },
        },
        timeout_s,
    )
    if policy_path:
        await _run(
            "policy",
            {"world": world.world_id, "req": {"ns": ns, "path": policy_path}},
            timeout_s,
        )
    await _run(
        "randomize", {"world": world.world_id, "req": {"ns": ns, **randomization}}, timeout_s
    )
    handle = RobotHandle(
        ns=ns, urdf_path=urdf_path, urdf_sha256=urdf_sha, randomization=randomization
    )
    _S.robots[ns] = handle
    return handle


async def step(duration_s: float, timeout_s: float = DEFAULT_TIMEOUT_S) -> SimTime:
    """Advance sim time synchronously and deterministically."""
    world = _world()
    if duration_s <= 0:
        raise SimStateError("duration_s must be > 0")
    out = await _run(
        "step",
        {"world": world.world_id, "req": {"multi_step": int(duration_s / 0.001)}},
        timeout_s,
    )
    return SimTime(sim_time_s=float(out.get("sim_time_s", 0.0)), steps=int(out.get("steps", 0)))


async def run_until(condition: str, timeout_s: float) -> RunResult:
    """Run until `condition` holds or sim time hits timeout_s. Never unbounded."""
    world = _world()
    if timeout_s <= 0:
        raise SimStateError("run_until requires a positive timeout_s (SPEC 6.3)")
    out = await _run(
        "run_until",
        {"world": world.world_id, "req": {"condition": condition, "timeout_s": timeout_s}},
        timeout_s,
    )
    return RunResult(
        condition=condition,
        satisfied=bool(out.get("satisfied", False)),
        sim_time_s=float(out.get("sim_time_s", 0.0)),
        timed_out=bool(out.get("timed_out", not out.get("satisfied", False))),
    )


async def read_sensor(
    robot: RobotHandle, sensor: str, timeout_s: float = DEFAULT_TIMEOUT_S
) -> SensorReading:
    """Read a sensor in SI units. Unknown sensor names are refused."""
    world = _world()
    _robot(robot.ns)
    if sensor not in SENSOR_UNITS:
        raise SimUnitError(f"sensor '{sensor}' has no declared SI unit; add it to SENSOR_UNITS")
    out = await _run(
        "sensor",
        {
            "world": world.world_id,
            "ns": robot.ns,
            "sensor": sensor,
            "topic": _topic(sensor, world.world_id, robot.ns),
        },
        timeout_s,
    )
    if "data" in out or "points" in out:
        # SPEC 6.3: an image or a point cloud comes back as a path. This is the
        # only door a bulk payload could arrive through once the camera is shut.
        raise SimUnitError(f"sensor '{sensor}' returned a payload; SPEC 6.3 requires a path")
    return SensorReading(
        sensor=sensor,
        unit=SENSOR_UNITS[sensor],
        values=[float(v) for v in out.get("values", [])],
        sim_time_s=float(out.get("sim_time_s", 0.0)),
    )


def _share_frame(path: str, ns: str, cam: str) -> str:
    """Copy the plugin's frame (it overwrites one file in this container's /tmp) into the shared
    work volume under a unique name, so the brain can read every frame of a recording."""
    frames = Path(os.getenv("NEML_FRAME_DIR", "/srv/neml/work/sim/frames"))
    try:
        frames.mkdir(parents=True, exist_ok=True)
        target = frames / f"{ns}_{cam}_{uuid.uuid4().hex[:12]}{Path(path).suffix}"
        shutil.copyfile(path, target)
    except OSError:
        return path  # no shared volume (a dev machine): the caller gets the plugin's own path
    return str(target)


async def capture_camera(
    robot: RobotHandle, cam: str, timeout_s: float = DEFAULT_TIMEOUT_S
) -> ImageRef:
    """Capture a frame and return its path. Visual profile only (SPEC 4.5)."""
    world = _world()
    _robot(robot.ns)
    if world.profile != "visual":
        raise SimProfileError(f"camera needs the 'visual' profile, world is '{world.profile}'")
    out = await _run(
        "camera", {"world": world.world_id, "req": {"ns": robot.ns, "camera": cam}}, timeout_s
    )
    if "data" in out or "payload" in out:
        raise SimUnitError("camera returned a payload; SPEC 6.3 requires a path reference")
    return ImageRef(
        path=_share_frame(str(out["path"]), robot.ns, cam),
        width_px=int(out.get("width_px", 0)),
        height_px=int(out.get("height_px", 0)),
        encoding=str(out.get("encoding", "png")),
    )


async def get_contacts(robot: RobotHandle, timeout_s: float = DEFAULT_TIMEOUT_S) -> list[Contact]:
    """Contact forces in Newtons, positions in metres."""
    world = _world()
    _robot(robot.ns)
    out = await _run(
        "contacts",
        {
            "world": world.world_id,
            "ns": robot.ns,
            "topic": _topic("contact", world.world_id, robot.ns),
        },
        timeout_s,
    )
    return [
        Contact(
            link=str(c["link"]),
            other_link=str(c.get("other_link", "")),
            force_N=Vec3(*(float(v) for v in c["force_N"])),
            position_m=Vec3(*(float(v) for v in c["position_m"])),
        )
        for c in out.get("contacts", [])
    ]


async def apply_wrench(
    link: str, force_N: Vec3, torque_Nm: Vec3, timeout_s: float = DEFAULT_TIMEOUT_S
) -> None:
    """Apply a wrench. Force in N, torque in Nm."""
    world = _world()
    await _run(
        "wrench",
        {
            "world": world.world_id,
            "req": {"link": link, "force": vars(force_N), "torque": vars(torque_Nm)},
        },
        timeout_s,
    )


async def get_metrics(robot: RobotHandle, timeout_s: float = DEFAULT_TIMEOUT_S) -> RunMetrics:
    """Run metrics plus the determinism verdict for this seed + sim_version."""
    world = _world()
    handle = _robot(robot.ns)
    out = await _run("metrics", {"world": world.world_id, "req": {"ns": robot.ns}}, timeout_s)
    values = {str(k): float(v) for k, v in (out.get("values") or out).items() if _is_number(v)}
    version = sim_version(world, handle)
    key = f"{version}:{world.seed}:{world.world_id}:{robot.ns}"
    baseline = _S.baselines.setdefault(key, values)
    return RunMetrics(
        seed=world.seed,
        sim_version=version,
        values=values,
        deterministic=within_tolerance(baseline, values),
        randomization=handle.randomization,
        policy_sha256=str(out.get("policy_sha256", "")),
    )


async def determinism_check(
    world_id: str,
    seed: int,
    urdf_path: str,
    profile: Literal["fast", "lidar", "visual"] = "fast",
    runs: int = DEFAULT_RUNS,
    duration_s: float = 10.0,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> DeterminismReport:
    """T-036: run the same seed `runs` times and rule on the 2% criterion.

    This is the harness the lab host executes against a real Gazebo; here it is
    driven by the injected runner, so its bookkeeping is testable without one.
    Every repeat gets a fresh world, because a reset that leaks state is exactly
    the defect this check exists to find.
    """
    if runs < 2:
        raise SimStateError("a determinism verdict needs at least two runs (T-036 asks for ten)")
    collected: list[dict[str, float]] = []
    version, randomization = "", {}
    for _ in range(runs):
        world = await load_world(world_id, seed, profile, timeout_s)
        try:
            robot = await spawn_robot(urdf_path, Pose(), "det", timeout_s)
            # The sim-time bound lives in the condition; timeout_s bounds the
            # call. Passing sim seconds as the call timeout would flake the
            # moment real_time_factor 0 runs faster or slower than 1x.
            await run_until(f"sim_time_s>={duration_s}", timeout_s)
            metrics = await get_metrics(robot, timeout_s)
        finally:
            await teardown(world, timeout_s)
        collected.append(metrics.values)
        version, randomization = metrics.sim_version, metrics.randomization
    return compare_runs(seed, version, collected, TOLERANCE, randomization)


def evolution_input(runs: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """SPEC 11.2 rule 3: drop every flagged run before an evolution decision.

    The sim server owns the verdict, so it owns the filter. The caller passes
    the sim_runs rows it was about to score and gets back only the rows that may
    legally carry weight.
    """
    return usable_runs(runs)


async def reset(handle: WorldHandle, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
    """Reset the world to its seeded initial state; robots are dropped."""
    world = _world()
    if handle.world_id != world.world_id:
        raise SimStateError(f"handle '{handle.world_id}' is not the live world '{world.world_id}'")
    await _run("reset", {"world": world.world_id, "req": {"reset": {"all": True}}}, timeout_s)
    _S.robots.clear()


async def teardown(handle: WorldHandle, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
    """Stop the world and release the GPU mutex if this run held it."""
    world = _world()
    if handle.world_id != world.world_id:
        raise SimStateError(f"handle '{handle.world_id}' is not the live world '{world.world_id}'")
    try:
        await _run("teardown", {"world": world.world_id, "req": {}}, timeout_s)
    finally:
        _S.world = None
        _S.robots.clear()
        if _S.gpu_held:
            _S.gpu_held = False
            await _lock().release("gazebo")


def sim_version(world: WorldHandle, robot: RobotHandle) -> str:
    """SPEC 11.2: gz version + world sha256 + URDF sha256."""
    raw = f"{world.gz_version}|{world.world_sha256}|{robot.urdf_sha256}"
    if world.physics:  # nominal runs keep their historical hash
        raw += "|" + json.dumps(world.physics, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# Exactly the twelve names SPEC 6.3 lists, no more: `determinism_check` is the
# T-036 lab harness (the __main__ block below) and `evolution_input` is the
# SPEC 11.2 rule 3 filter the brain imports. Neither is an MCP tool, and
# brain/tests/mcp/test_contract.py fails if either is added here.
TOOLS: dict[str, Callable[..., Any]] = {
    "set_seed": set_seed,
    "load_world": load_world,
    "spawn_robot": spawn_robot,
    "step": step,
    "run_until": run_until,
    "read_sensor": read_sensor,
    "capture_camera": capture_camera,
    "get_contacts": get_contacts,
    "apply_wrench": apply_wrench,
    "get_metrics": get_metrics,
    "reset": reset,
    "teardown": teardown,
}

app = make_app("neml-mcp-sim", VERSION, TOOLS)

if __name__ == "__main__":  # pragma: no cover
    import argparse
    import asyncio
    import json

    parser = argparse.ArgumentParser(description="neml-mcp-sim (SPEC 6.3)")
    parser.add_argument("--determinism-check", action="store_true", help="T-036 harness, then exit")
    parser.add_argument("--world", default="flat")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--urdf", default="", help="URDF to spawn; its sha256 is in sim_version")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--duration-s", type=float, default=10.0)
    parser.add_argument("--timeout-s", type=float, default=DEFAULT_TIMEOUT_S)
    args = parser.parse_args()

    if args.determinism_check:
        if not args.urdf:
            parser.error("--determinism-check needs --urdf; sim_version is built from its sha256")
        report = asyncio.run(
            determinism_check(
                args.world,
                args.seed,
                args.urdf,
                "fast",
                args.runs,
                args.duration_s,
                args.timeout_s,
            )
        )
        print(json.dumps(vars(report), indent=2))
        raise SystemExit(0 if report.deterministic else 1)

    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT)
