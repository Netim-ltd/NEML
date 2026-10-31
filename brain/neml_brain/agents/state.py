# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# NEML_SPEC.md 8.4 - LangGraph state. The 25 node-step cap is enforced here,
# in the state model, so no node can opt out of it by convention.

import operator
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, field_validator

# SPEC 8.4: "Maksimum dugum adimi: 25 (sonsuz dongu korumasi)."
MAX_STEPS = 25

# SPEC 8.4 draws the SIMULATE failure edge looping back into SIMULATE but does
# not bound it; the only spec bound is MAX_STEPS. A 600 s sim (SPEC 6.5 timeout)
# retried ~19 times before the cap fires is not a useful failure mode.
# ponytail: fixed retry count, make it a campaign parameter if evolution ever
# needs a different budget per run.
MAX_SIM_RETRIES = 2

# SPEC 4.3 stage 1 - the router may only emit one of these (guided_choice).
INTENT = [
    "create_task",
    "update_task",
    "cancel_task",
    "query_status",
    "query_telemetry",
    "query_skill",
    "mech_param_change",
    "elec_param_change",
    "explain",
    "unknown",
]


class StepLimitExceeded(RuntimeError):
    """Raised when a flow exceeds the SPEC 8.4 cap of 25 node steps."""


class GraphState(BaseModel):
    """State of one command flowing through the SPEC 8.4 graph.

    Checkpointed to PostgreSQL after every node, so the whole model must stay
    JSON-serialisable: no live handles, no clients, no open files.
    """

    model_config = ConfigDict(extra="forbid")

    # --- input -------------------------------------------------------------
    # SPEC 5.4: `command` is untrusted data. It is never interpolated into a
    # prompt outside an <untrusted_data> block (see orchestrator._untrusted).
    command: str
    actor: str = "user"
    thread_id: str | None = None

    # --- router ------------------------------------------------------------
    intent: str | None = None
    branch: str | None = None
    agent: str | None = None

    # --- design chain ------------------------------------------------------
    params: dict[str, Any] = {}
    artifacts: list[dict[str, Any]] = []
    validation: dict[str, Any] | None = None
    sim: dict[str, Any] | None = None
    sim_retries: int = 0

    # --- SPEC 5.2 approval gate -------------------------------------------
    approval_id: str | None = None
    approval: dict[str, Any] | None = None

    # --- terminal ----------------------------------------------------------
    result: dict[str, Any] | None = None

    # Reducer: every node returns {"steps": 1}; LangGraph sums them.
    steps: Annotated[int, operator.add] = 0

    @field_validator("steps")
    @classmethod
    def _cap_steps(cls, value: int) -> int:
        # StepLimitExceeded is not a ValueError, so Pydantic lets it through
        # unwrapped instead of folding it into a ValidationError.
        if value > MAX_STEPS:
            raise StepLimitExceeded(f"node step {value} exceeds SPEC 8.4 cap of {MAX_STEPS}")
        return value
