# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# NEML_SPEC.md 8.2 - swarm agent. Multi-robot task assignment. The plan is
# deterministic arithmetic (no model), and the dispatch goes out over the MCP
# boundary to ros2_ws/src/neml_swarm, which owns the robot lease: this module
# never tracks who holds what, it asks and records the answer.

from itertools import cycle
from typing import Any

from pydantic import BaseModel, ConfigDict

from neml_brain.agents.base import Deps, register
from neml_brain.agents.state import GraphState

# A robot in any other state is busy, charging, faulted or e-stopped.
ASSIGNABLE = frozenset({"idle", "ready"})


class SwarmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mission_id: str
    robot_ids: list[str]
    roles: list[str] = ["worker"]


class SwarmAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    robot_id: str
    role: str


class SwarmPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mission_id: str
    assignments: list[SwarmAssignment] = []
    dispatched: bool = False
    reason: str | None = None


async def node(state: GraphState, deps: Deps) -> dict[str, Any]:
    """Plan always, dispatch only behind a decided approval (SPEC 5.2 / 5.4).

    robot.assign_task is requires_approval in tools.yaml, so Agent.call refuses
    it without an approval id; the plan is still returned, which is what the
    approval screen shows the operator.
    """
    request = SwarmRequest.model_validate(state.params)
    fleet = await AGENT.call(deps, "robot.read", {"robot_ids": request.robot_ids})
    ready = [
        robot["id"]
        for robot in fleet.get("robots", [])
        if robot.get("id") in request.robot_ids and robot.get("state") in ASSIGNABLE
    ]
    roles = cycle(request.roles or ["worker"])
    plan = SwarmPlan(
        mission_id=request.mission_id,
        assignments=[SwarmAssignment(robot_id=r, role=next(roles)) for r in ready],
    )

    if not state.approval_id:
        plan.reason = "no approval on record; robot.assign_task not called"
    else:
        for assignment in plan.assignments:
            await AGENT.call(
                deps,
                "robot.assign_task",
                {
                    "mission_id": plan.mission_id,
                    "robot_id": assignment.robot_id,
                    "role": assignment.role,
                },
                approval_id=state.approval_id,
            )
        plan.dispatched = True
    return {"result": plan.model_dump(mode="json"), "steps": 1}


# Owner decision 3 grants [db.read, robot.read] plus robot.assign_task behind an
# approval - the same static-grant-gated-on-an-approval-id rule as printer.start.
AGENT = register(
    "swarm",
    input_schema=SwarmRequest,
    output_schema=SwarmPlan,
    tools=("db.read", "robot.read", "robot.assign_task"),
    node=node,
)
