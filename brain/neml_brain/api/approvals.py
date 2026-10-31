# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Human approval gate (SPEC 8.3, 5.2).

Nothing that reaches hardware passes without a row here. The gate is enforced
in safety/, in code -- not by asking the model nicely.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from neml_brain.api import deps
from neml_brain.api.metrics import APPROVAL_PENDING_COUNT
from neml_brain.api.problem import Problem

router = APIRouter(prefix="/v1/approvals", tags=["approvals"])


class ApprovalDecision(BaseModel):
    decision: Literal["approved", "rejected"]
    decided_by: str = Field(
        min_length=1,
        description="Authenticated identity from the .NET API (SPEC 5.5). Level 4 is owner-only; "
        "safety/ re-checks the level against the role, this endpoint does not trust the caller.",
    )
    note: str | None = Field(default=None, max_length=1000)


@router.get("")
async def pending_approvals(repo: deps.Repo) -> list[dict[str, Any]]:
    """Undecided, unexpired requests. Expiry is swept by the scheduler, so a
    stale request can never look actionable here."""
    approvals = list(await repo.pending_approvals())
    APPROVAL_PENDING_COUNT.set(len(approvals))
    return approvals


@router.get("/{approval_id}")
async def get_approval(approval_id: str, repo: deps.Repo) -> dict[str, Any]:
    approval = await repo.get_approval(approval_id)
    if approval is None:
        raise Problem(404, "Not Found", f"No approval with id '{approval_id}'.")
    return dict(approval)


@router.post("/{approval_id}/decide")
async def decide_approval(
    approval_id: str, body: ApprovalDecision, safety: deps.Safety
) -> dict[str, Any]:
    """`expired` is not a decision a human can send -- only the sweep sets it
    (SPEC 5.2), so an approval that timed out is refused here with 409."""
    result = await safety.decide_approval(
        approval_id=approval_id,
        decision=body.decision,
        decided_by=body.decided_by,
        note=body.note,
    )
    if result is None:
        raise Problem(404, "Not Found", f"No approval with id '{approval_id}'.")
    if result.get("decision") not in ("approved", "rejected"):
        raise Problem(
            409,
            "Conflict",
            f"Approval '{approval_id}' is already {result.get('decision')}.",
            approval=dict(result),
        )
    return dict(result)
