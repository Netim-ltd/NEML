# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""POST /v1/command — natural language into the SPEC 4.3 pipeline."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from neml_brain.api import deps
from neml_brain.api.problem import Problem
from neml_brain.logging import current_correlation_id

router = APIRouter(prefix="/v1/command", tags=["command"])


class CommandRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    actor: str = Field(min_length=1, description="user:mg — written to audit_log (SPEC 5.4).")
    robot_id: str | None = None


@router.post("", status_code=202)
async def submit_command(
    body: CommandRequest, orchestrator: deps.Orchestrator, budget: deps.Budget
) -> dict[str, Any]:
    """Hand the text to the LangGraph orchestrator and return what it decided.

    This endpoint does not talk to the model. It never has. The SPEC 4.3
    pipeline lives in agents/orchestrator.py: ROUTER classifies with
    `guided_choice`, PARAM_FILL fills a JSON Schema with `guided_json`, and
    GENERATE is deterministic Python with no model in the loop. Giving the
    model a tool list and letting it choose is forbidden (SPEC 6.5).

    `body.text` is untrusted input (SPEC 5.4). The orchestrator wraps it in an
    <untrusted_data> block; it is never read as an instruction.
    """
    if not await budget.allow("llm_tokens"):
        # SPEC 14.4 — over the daily limit the request is refused and the queue waits.
        raise Problem(
            429,
            "Budget Exhausted",
            "Daily LLM token budget is spent; the request was not sent to the model.",
            resource="llm_tokens",
        )
    # Imported here: llm.provider imports api.metrics, and api/__init__ imports this module.
    from neml_brain.llm.provider import SchemaViolation

    try:
        result = await orchestrator.handle_command(
            text=body.text,
            actor=body.actor,
            robot_id=body.robot_id,
            correlation_id=current_correlation_id(),
        )
    except SchemaViolation as exc:
        # The model answered outside its grammar / schema. Nothing was generated or stored.
        raise Problem(502, "Model Output Rejected", str(exc)[:300]) from exc
    return dict(result)
