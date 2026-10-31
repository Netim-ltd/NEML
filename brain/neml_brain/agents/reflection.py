# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# NEML_SPEC.md 8.2 / 14.6 - reflection agent. Step 2 of the learning record:
# tag a failed run with the SPEC 4.4 `failure_tag` profile (guided_choice, 64
# tokens). Classification only - the model never explains, never proposes.

from typing import Any

from pydantic import BaseModel, ConfigDict

from neml_brain.agents.base import Deps, register, untrusted
from neml_brain.agents.state import GraphState

# Owner decision 4: the choice list is the profile's, not this module's. It was
# defined here once and drifted; neml_brain.llm.profiles now owns the only copy.
from neml_brain.llm.profiles import FAILURE_MODES, check_failure_mode

PROFILE = "failure_tag"


class FailureContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    # Untrusted: log lines and sensor text (SPEC 5.4).
    evidence: str


class FailureTag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    mode: str


async def node(state: GraphState, deps: Deps) -> dict[str, Any]:
    context = FailureContext.model_validate(state.params)
    mode = await deps.llm.classify(
        untrusted("Tag the failure mode of this run.", context.evidence),
        FAILURE_MODES,
        profile=PROFILE,
    )
    # guided_choice already makes an off-list label undecodable; this refuses it
    # a second time so a downgraded provider (SPEC 4.7) cannot widen the enum.
    tag = FailureTag(run_id=context.run_id, mode=check_failure_mode(mode))
    return {"result": tag.model_dump(mode="json"), "steps": 1}


# SPEC 5.4 grants reflection [db.read, memory.write]: it reads the failed run
# and writes the tagged chunk (SPEC 14.6 step 3). Nothing else.
AGENT = register(
    "reflection",
    input_schema=FailureContext,
    output_schema=FailureTag,
    tools=("db.read", "memory.write"),
    node=node,
)
