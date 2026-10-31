# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""POST /v1/sim/run — one-shot simulation (SPEC 8.3, 6.3, 4.5)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from neml_brain.api import deps
from neml_brain.api.problem import Problem

router = APIRouter(prefix="/v1/sim", tags=["sim"])


class Physics(BaseModel):
    """SPEC 11.3 calibration parameters. Bounds are the calibration's own search
    box (reality_gap.PARAM_BOUNDS), so a fit can never ask for a negative friction."""

    model_config = ConfigDict(extra="forbid")
    friction: float = Field(ge=0.05, le=2.0)
    joint_damping: float = Field(ge=0.0, le=10.0)
    motor_gain: float = Field(ge=0.1, le=3.0)
    body_inertia_correction: float = Field(ge=0.5, le=2.0)
    comms_latency_s: float = Field(ge=0.0, le=0.1)


class SimRunRequest(BaseModel):
    # Unknown controls must fail validation: a field the simulator ignores would
    # make a calibration iteration run the same world.
    model_config = ConfigDict(extra="forbid")
    world_id: str = Field(min_length=1)
    seed: int = Field(
        ge=0, description="Same seed + same sim version hash = same result (SPEC 6.3)."
    )
    profile: Literal["fast", "lidar", "visual"] = "fast"
    genome_id: str | None = None
    skill_id: str | None = None
    duration_s: float = Field(default=60.0, gt=0, le=3600)
    physics: Physics | None = Field(
        default=None,
        description="SPEC 11.3 calibrated physics for this run; echoed back and folded "
        "into sim_version. Omit to run on the nominals.",
    )


@router.post("/run", status_code=201)
async def run_sim(body: SimRunRequest, sim: deps.Sim, budget: deps.Budget) -> dict[str, Any]:
    """Runs headless through neml-mcp-sim. The `visual` profile needs the GPU,
    so the sim client takes the GPU mutex and stops vLLM for the duration
    (SPEC 4.5); ~40 s of restart cost is part of the run, not a surprise."""
    if not await budget.allow("sim_runs"):
        raise Problem(
            429,
            "Budget Exhausted",
            "Daily simulation run budget is spent.",
            resource="sim_runs",
        )
    if body.profile == "visual" and not await budget.allow("gpu_hours"):
        raise Problem(
            429,
            "Budget Exhausted",
            "Daily GPU budget is spent; the `visual` profile needs the GPU.",
            resource="gpu_hours",
        )
    return dict(await sim.run_once(body.model_dump(mode="json")))
