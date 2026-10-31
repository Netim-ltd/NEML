# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# NEML_SPEC.md 8.2 / 4.5 - perception agent. It owns the one sim profile that
# needs the GPU: `visual`. vLLM and a rendering Gazebo cannot share 3 GB, so the
# node takes the SPEC 4.5 mutex (which stops neml-vllm) for the capture and
# gives it back immediately - the ~40 s restart is the planned cost of one run.

from typing import Any

from pydantic import BaseModel, ConfigDict

from neml_brain.agents.base import Deps, register
from neml_brain.agents.state import GraphState

# SPEC 4.5 table: `fast` and `lidar` render on CPU, `visual` needs the GPU.
GPU_PROFILE = "visual"
CONSUMER = "perception"


class PerceptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    robot_id: str
    topic: str  # ROS 2 sensor topic, e.g. /camera/image_raw
    profile: str = "sim_visual"


class Detection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    confidence: float
    bbox: tuple[float, float, float, float]


class PerceptionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    robot_id: str
    # SPEC 6.3: capture_camera returns a reference, never pixel data.
    image_ref: str | None = None
    detections: list[Detection] = []


async def node(state: GraphState, deps: Deps) -> dict[str, Any]:
    """Capture one frame under the SPEC 4.5 GPU mutex.

    ponytail: no detector lives in this tree, so `detections` is whatever the sim
    server reports alongside the frame (ground truth in sim) and is empty
    otherwise. Add the model here when a perception skill needs real boxes.
    """
    request = PerceptionRequest.model_validate(state.params)
    # Held across the capture only. Acquiring inside the try would release a lock
    # the node never took if acquire() itself failed.
    await deps.gpu.acquire(CONSUMER, profile=GPU_PROFILE)
    try:
        frame = await AGENT.call(
            deps,
            "sim.capture_camera",
            {"robot": request.robot_id, "cam": request.topic, "profile": request.profile},
        )
    finally:
        await deps.gpu.release(CONSUMER)

    result = PerceptionResult(
        robot_id=request.robot_id,
        image_ref=frame.get("image_ref"),
        detections=[Detection.model_validate(d) for d in frame.get("detections", [])],
    )
    return {"result": result.model_dump(mode="json"), "steps": 1}


# Owner decision 3 grants [db.read, sim.read, sim.capture_camera]: it may look at
# the world and take a picture of it, and cannot move anything.
AGENT = register(
    "perception",
    input_schema=PerceptionRequest,
    output_schema=PerceptionResult,
    tools=("db.read", "sim.read", "sim.capture_camera"),
    node=node,
)
