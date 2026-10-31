# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The lab's simulation stage: a recorded run of a model's chassis in a Gazebo world.

What is measured: whether the chassis reaches the goal in a world under SPEC 11.4 domain
randomisation, driven by an attested policy, photographed every half second. The chassis is a
wheeled stand-in of the model's mass (there is no walking controller yet, like
platform/physics.py scenarios). Nothing about a design's geometry is scored here: designs are made
by the model through the CAD MCP and judged by the analysts and the round table.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

from neml_brain.evolution.worlds import WorldStore
from neml_brain.platform.core import Scope
from neml_brain.platform.physics import GazeboPhysicsRunner, McpCaller
from neml_brain.platform.policy import LinearPolicy

SCOPE = Scope("neml", "evolution")

# A wheeled stand-in for the chassis: same mass, same plugin interface as test_rover.sdf.
_CHASSIS_SDF = """<?xml version="1.0"?>
<sdf version="1.10"><model name="evo_chassis">
<link name="base_link"><pose>0 0 0.1 0 0 0</pose>
<inertial><mass>{mass}</mass><inertia><ixx>{ixx}</ixx><iyy>{iyy}</iyy><izz>{izz}</izz>
<ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia></inertial>
<collision name="c"><geometry><box><size>0.4 0.2 0.08</size></box></geometry></collision>
<visual name="v"><geometry><box><size>0.4 0.2 0.08</size></box></geometry></visual>{camera}</link>
<link name="left_wheel"><pose>0 0.12 0.1 -1.5708 0 0</pose>
<inertial><mass>0.2</mass><inertia><ixx>0.0005</ixx><iyy>0.0005</iyy><izz>0.0008</izz>
<ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia></inertial>
<collision name="c"><geometry><cylinder><radius>0.1</radius>
<length>0.04</length></cylinder></geometry>
<surface><friction><ode><mu>1.0</mu><mu2>1.0</mu2></ode></friction></surface></collision>
<visual name="v"><geometry><cylinder><radius>0.1</radius>
<length>0.04</length></cylinder></geometry></visual></link>
<link name="right_wheel"><pose>0 -0.12 0.1 -1.5708 0 0</pose>
<inertial><mass>0.2</mass><inertia><ixx>0.0005</ixx><iyy>0.0005</iyy><izz>0.0008</izz>
<ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia></inertial>
<collision name="c"><geometry><cylinder><radius>0.1</radius>
<length>0.04</length></cylinder></geometry>
<surface><friction><ode><mu>1.0</mu><mu2>1.0</mu2></ode></friction></surface></collision>
<visual name="v"><geometry><cylinder><radius>0.1</radius>
<length>0.04</length></cylinder></geometry></visual></link>
<link name="caster"><pose>-0.17 0 0.05 0 0 0</pose>
<inertial><mass>0.05</mass><inertia><ixx>0.0001</ixx><iyy>0.0001</iyy><izz>0.0001</izz>
<ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia></inertial>
<collision name="c"><geometry><sphere><radius>0.05</radius></sphere></geometry>
<surface><friction><ode><mu>0</mu><mu2>0</mu2></ode></friction></surface></collision>
<visual name="v"><geometry><sphere><radius>0.05</radius></sphere></geometry></visual></link>
<joint name="left_wheel_joint" type="revolute"><parent>base_link</parent><child>left_wheel</child>
<axis><xyz>0 0 1</xyz><limit><lower>-1e16</lower><upper>1e16</upper></limit></axis></joint>
<joint name="right_wheel_joint" type="revolute"><parent>base_link</parent><child>right_wheel</child>
<axis><xyz>0 0 1</xyz><limit><lower>-1e16</lower><upper>1e16</upper></limit></axis></joint>
<joint name="caster_joint" type="ball"><parent>base_link</parent><child>caster</child></joint>
<plugin filename="gz-sim-diff-drive-system" name="gz::sim::systems::DiffDrive">
<left_joint>left_wheel_joint</left_joint><right_joint>right_wheel_joint</right_joint>
<wheel_separation>0.24</wheel_separation><wheel_radius>0.1</wheel_radius></plugin>
</model></sdf>
"""


# A chase camera: behind and above the chassis, tilted down, so the robot itself and the course
# ahead are both in frame (a camera on the nose only shows the wall it is facing).
_CAMERA = """
<sensor name="cam" type="camera"><pose>-0.75 0 0.55 0 0.5 0</pose><update_rate>10</update_rate>
<always_on>true</always_on><camera><horizontal_fov>1.3</horizontal_fov>
<image><width>320</width><height>240</height></image><clip><near>0.05</near><far>30</far>
</clip></camera></sensor>"""

# Where the chassis starts in each world: the maze's west wall is at x=0, so it starts inside the
# first corridor instead of in the wall. (x, y, yaw)
WORLD_START: dict[str, tuple[float, float, float]] = {"maze": (0.4, -1.4, 0.0)}

WORLDS = ("flat", "maze", "obstacle_low", "ramp_10deg", "rough_terrain")
RECORD_STEP_S = 0.5
MAX_RECORD_S = 20.0


def genome_hash(body: Mapping[str, Any]) -> str:
    """SPEC 13.3: content hash, the `hash` field itself excluded (same as neml-mcp-genome)."""
    canonical = json.dumps(
        {k: v for k, v in body.items() if k != "hash"},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:7]


class BodyEvaluator:
    """Runs the chassis in Gazebo and records it."""

    def __init__(
        self,
        mcp: McpCaller,
        work_dir: Path,
        world_id: str = "flat",
        duration_s: float = 6.0,
        timeout_s: float = 300.0,
    ) -> None:
        self.mcp = mcp
        self.dir = work_dir / "evolution"
        self.world_id, self.duration_s = world_id, duration_s
        self._runner = GazeboPhysicsRunner(mcp, {}, {}, self.dir / "policies", timeout_s)

    # --------------------------------------------------------------- Gazebo
    def _chassis(self, mass_kg_: float, camera: bool = False) -> Path:
        tag = "_cam2" if camera else ""
        path = self.dir / "models" / f"chassis_{round(mass_kg_ * 1000)}g{tag}.sdf"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            # box 0.4 x 0.2 x 0.08 m, solid
            ixx, iyy, izz = (
                mass_kg_ / 12 * (0.2**2 + 0.08**2),
                mass_kg_ / 12 * (0.4**2 + 0.08**2),
                mass_kg_ / 12 * (0.4**2 + 0.2**2),
            )
            path.write_text(
                _CHASSIS_SDF.format(
                    mass=mass_kg_, ixx=ixx, iyy=iyy, izz=izz, camera=_CAMERA if camera else ""
                )
            )
        return path

    async def record(
        self,
        body_kg: float,
        seed: int,
        world_id: str = "flat",
        seconds: float = 6.0,
        label: str = "",
        on_frame: Callable[[Any], Awaitable[None]] | None = None,
    ) -> tuple[Path, dict[str, float]]:
        """Run the chassis in the `visual` profile, photographing it every half second.

        Returns the annotated GIF and the run's final metrics. The run is the same physics as
        `sim` (same policy, same seed, same randomisation); only the camera is added.
        """
        from neml_brain.evolution.recording import Frame, annotate, build_gif, read_frame

        if world_id not in WORLDS and world_id not in WorldStore().index():
            raise ValueError(f"unknown world {world_id!r}; choose one of {WORLDS}")
        seconds = min(max(seconds, RECORD_STEP_S), MAX_RECORD_S)
        robot_type = f"rec_{round(body_kg * 1000)}g_{seed}"
        policy = LinearPolicy.empty(robot_type, ("forward", "stop"), 5)
        digest = self._runner.register(policy)
        policy_path = self.dir / "policies" / f"{digest}.json"
        policy_path.parent.mkdir(parents=True, exist_ok=True)
        policy_path.write_bytes(policy.to_bytes())
        self._runner.policies.clear()
        t = self._runner.timeout_s
        frames: list[Frame] = []
        values: dict[str, float] = {}
        world = await self.mcp.call(
            "sim", "load_world", {"world_id": world_id, "seed": seed, "profile": "visual"}, t
        )
        try:
            robot = await self.mcp.call(
                "sim",
                "spawn_robot",
                {
                    "urdf_path": str(self._chassis(body_kg, camera=True)),
                    "pose": {
                        "x_m": WORLD_START.get(world_id, (0.0, 0.0, 0.0))[0],
                        "y_m": WORLD_START.get(world_id, (0.0, 0.0, 0.0))[1],
                        "z_m": 0.05,
                        "roll_rad": 0.0,
                        "pitch_rad": 0.0,
                        "yaw_rad": WORLD_START.get(world_id, (0.0, 0.0, 0.0))[2],
                    },
                    "ns": robot_type,
                    "policy_path": str(policy_path),
                },
                t,
            )
            for i in range(int(seconds / RECORD_STEP_S)):
                await self.mcp.call("sim", "step", {"duration_s": RECORD_STEP_S}, t)
                image = await self.mcp.call(
                    "sim", "capture_camera", {"robot": robot, "cam": "cam"}, t
                )
                metrics = await self.mcp.call("sim", "get_metrics", {"robot": robot}, t)
                values = {k: float(v) for k, v in dict(metrics.get("values", {})).items()}
                frames.append(
                    Frame(
                        read_frame(image["path"]), (i + 1) * RECORD_STEP_S, values.get("x_m", 0.0)
                    )
                )
                if on_frame is not None:
                    await on_frame(annotate(frames[-1], label or world_id))
                Path(image["path"]).unlink(missing_ok=True)  # the shared copy has done its job
        finally:
            await self.mcp.call("sim", "teardown", {"handle": world}, t)
        out = self.dir / "media" / f"{robot_type}_{world_id}.gif"
        return build_gif(frames, label or f"{world_id} {body_kg:.2f} kg", out), values
