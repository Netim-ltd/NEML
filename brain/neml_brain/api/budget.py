# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""GET /v1/budget — daily budget usage (SPEC 8.3, 14.4)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from neml_brain.api import deps
from neml_brain.api.metrics import BUDGET_USED_RATIO

router = APIRouter(prefix="/v1/budget", tags=["budget"])


@router.get("")
async def budget_usage(budget: deps.Budget) -> dict[str, Any]:
    """Six resources, reset 00:00 TRT. The mobile dashboard draws these as bars
    and a notification goes out at 90% (SPEC 14.4)."""
    snapshot: dict[str, Any] = dict(await budget.snapshot())
    for resource, usage in snapshot.get("resources", {}).items():
        ratio = usage.get("ratio")
        if ratio is not None:
            BUDGET_USED_RATIO.labels(resource=resource).set(float(ratio))
    return snapshot
