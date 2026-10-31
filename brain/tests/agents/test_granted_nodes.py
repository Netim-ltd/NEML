# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Owner decision 3 (amends SPEC 5.4): perception and swarm have a
# tool grant, so they have a node. These tests cover what the grant lets each one
# do and what the approval gate still stops.

import dataclasses
from typing import Any

import pytest

from neml_brain.agents import perception, swarm
from neml_brain.agents.state import GraphState
from tests.agents.conftest import FakeMcp

# --- perception (SPEC 4.5) -------------------------------------------------


async def test_perception_holds_the_gpu_mutex_around_the_capture(deps, gpu):
    deps = dataclasses.replace(
        deps, mcp=FakeMcp({"sim.capture_camera": {"image_ref": "/srv/neml/artifacts/f1.png"}})
    )
    state = GraphState(command="look", params={"robot_id": "r1", "topic": "/camera/image_raw"})

    out = await perception.node(state, deps)

    assert gpu.events == [("acquire", "perception", "visual"), ("release", "perception")]
    assert gpu.held == 0
    assert deps.mcp.tools() == ["sim.capture_camera"]
    assert out["result"] == {
        "robot_id": "r1",
        "image_ref": "/srv/neml/artifacts/f1.png",
        "detections": [],
    }


async def test_perception_releases_the_gpu_when_the_capture_fails(deps, gpu):
    class Boom(FakeMcp):
        async def call(self, tool, params):
            await super().call(tool, params)
            raise RuntimeError("gazebo died")

    deps = dataclasses.replace(deps, mcp=Boom())
    state = GraphState(command="look", params={"robot_id": "r1", "topic": "/camera/image_raw"})

    with pytest.raises(RuntimeError):
        await perception.node(state, deps)
    assert gpu.held == 0, "vLLM would stay stopped forever"
    assert gpu.events[-1] == ("release", "perception")


# --- swarm -----------------------------------------------------------------


FLEET = {
    "robots": [
        {"id": "r1", "state": "idle"},
        {"id": "r2", "state": "charging"},
        {"id": "r3", "state": "ready"},
    ]
}


def _swarm_params() -> dict[str, Any]:
    return {"mission_id": "m-1", "robot_ids": ["r1", "r2", "r3"], "roles": ["scout", "carrier"]}


async def test_swarm_plans_only_over_assignable_robots(deps):
    deps = dataclasses.replace(deps, mcp=FakeMcp({"robot.read": FLEET}))
    state = GraphState(command="assign", params=_swarm_params())

    out = await swarm.node(state, deps)

    assert out["result"]["assignments"] == [
        {"robot_id": "r1", "role": "scout"},
        {"robot_id": "r3", "role": "carrier"},
    ]
    assert out["result"]["dispatched"] is False
    assert deps.mcp.tools() == ["robot.read"], "no approval, no robot.assign_task"


async def test_swarm_dispatches_once_an_approval_exists(deps, db):
    deps = dataclasses.replace(deps, mcp=FakeMcp({"robot.read": FLEET}))
    state = GraphState(command="assign", params=_swarm_params(), approval_id="apr-4")

    out = await swarm.node(state, deps)

    assert out["result"]["dispatched"] is True
    assert deps.mcp.tools() == ["robot.read", "robot.assign_task", "robot.assign_task"]
    assert {row["approval_id"] for row in db.audits if row["action"] == "robot.assign_task"} == {
        "apr-4"
    }
