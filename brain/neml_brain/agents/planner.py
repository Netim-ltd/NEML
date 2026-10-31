# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# NEML_SPEC.md 8.2 / 14.2 - planner agent. Ranks discovered task candidates
# with the SPEC 14.2 priority formula. Deterministic arithmetic, no model:
# the LLM never orders the queue.

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from neml_brain.agents.base import Deps, register
from neml_brain.agents.state import GraphState


class TaskCandidate(BaseModel):
    """One SPEC 14.2 discovery-source output plus its scoring inputs."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str  # repair | exploration | evolution | maintenance | calibration | human
    is_human: bool = False
    urgency: float = Field(default=0.0, ge=0.0, le=1.0)
    expected_gain: float = Field(default=0.0, ge=0.0, le=1.0)
    staleness: float = Field(default=0.0, ge=0.0, le=1.0)
    cheapness: float = Field(default=0.0, ge=0.0, le=1.0)
    blocked: bool = False
    created_at: datetime


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[TaskCandidate] = []


class ScoredTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    priority: float


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ordered: list[ScoredTask] = []


def priority(candidate: TaskCandidate) -> float:
    """SPEC 14.2 priority formula, verbatim."""
    return (
        100 * candidate.is_human
        + 40 * candidate.urgency
        + 25 * candidate.expected_gain
        + 15 * candidate.staleness
        + 10 * candidate.cheapness
        - 50 * candidate.blocked
    )


def rank(request: PlanRequest) -> Plan:
    """P DESC, ties broken by created_at ASC (SPEC 14.2)."""
    ordered = sorted(request.candidates, key=lambda c: (-priority(c), c.created_at))
    return Plan(ordered=[ScoredTask(id=c.id, priority=priority(c)) for c in ordered])


async def node(state: GraphState, deps: Deps) -> dict[str, Any]:
    return {
        "result": rank(PlanRequest.model_validate(state.params)).model_dump(mode="json"),
        "steps": 1,
    }


# SPEC 5.4 grants planner exactly [db.read, sim.read, skill.read].
AGENT = register(
    "planner",
    input_schema=PlanRequest,
    output_schema=Plan,
    tools=("db.read", "sim.read", "skill.read"),
    node=node,
)
