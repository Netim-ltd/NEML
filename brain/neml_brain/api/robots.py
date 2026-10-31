# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Robot list, detail and the SOFTWARE e-stop (SPEC 8.3, 5.1)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from neml_brain.api import deps
from neml_brain.api.metrics import ROBOT_BATTERY_SOC
from neml_brain.api.problem import Problem

router = APIRouter(prefix="/v1/robots", tags=["robots"])


class EstopRequest(BaseModel):
    actor: str = Field(min_length=1, description="user:mg — written to audit_log (SPEC 5.4).")
    reason: str = Field(min_length=1, max_length=500)


class SafetyCheckRequest(BaseModel):
    """What a person verified at the bench. Three booleans and a name: this is an
    attestation, so every field is required and none has a default."""

    estop_ok: bool = Field(description="Mushroom button and bench button both cut motor power.")
    watchdog_ok: bool = Field(description="Heartbeat cut: the relay opened within 150 ms.")
    current_limit_ok: bool = Field(description="Hardware current comparator tripped on test load.")
    performed_by: str = Field(min_length=1, description="The person who ran the test.")


@router.get("")
async def list_robots(repo: deps.Repo) -> list[dict[str, Any]]:
    robots: list[dict[str, Any]] = await repo.list_robots()
    for robot in robots:
        soc = robot.get("battery_soc")
        if soc is not None:
            ROBOT_BATTERY_SOC.labels(robot_id=robot["id"]).set(float(soc))
    return robots


@router.get("/{robot_id}")
async def get_robot(robot_id: str, repo: deps.Repo) -> dict[str, Any]:
    robot = await repo.get_robot(robot_id)
    if robot is None:
        raise Problem(404, "Not Found", f"No robot with id '{robot_id}'.")
    return dict(robot)


@router.post("/{robot_id}/safety-check", status_code=201)
async def record_safety_check(
    robot_id: str, body: SafetyCheckRequest, safety: deps.Safety
) -> dict[str, Any]:
    """Record the SAFETY.md section 0 test. Without a fresh passing row the brain
    refuses physical tasks in code (safety/preflight.py). A failing test is recorded
    as well, because the newest row decides."""
    result = await safety.record_safety_check(robot_id=robot_id, **body.model_dump())
    if result is None:
        raise Problem(404, "Not Found", f"No robot with id '{robot_id}'.")
    return dict(result)


@router.post("/{robot_id}/estop", status_code=202)
async def software_estop(robot_id: str, body: EstopRequest, safety: deps.Safety) -> dict[str, Any]:
    """SOFTWARE stop. Publishes the e-stop event on the ROS 2 stack, moves the
    robot to state `estop` and cancels its running task.

    This is L1. It is NOT the safety system.

    The L0 hardware e-stop of SPEC 5.1 -- the NC mushroom button that opens the
    motor relay, and the ATmega328P watchdog that opens the same relay when a
    heartbeat is more than 150 ms late -- is electrically independent of this
    endpoint and of every other line of code in this repository. It cuts motor
    power whether or not this process is running, reachable or correct. Nothing
    here can arm, disarm, delay or override it, and no agent may touch it
    (`safety.*` is in global_forbidden, SPEC 5.4).

    Treat this endpoint as best-effort convenience. The button is the stop.
    """
    result = await safety.software_estop(robot_id=robot_id, actor=body.actor, reason=body.reason)
    if result is None:
        raise Problem(404, "Not Found", f"No robot with id '{robot_id}'.")
    return {"robot_id": robot_id, "layer": "L1-software", "l0_independent": True, **dict(result)}
