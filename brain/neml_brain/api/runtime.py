# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""POST /v1/runtime/llm/{start|stop} — GPU mutex management (SPEC 8.3, 4.5).

3 GB of VRAM holds vLLM or a rendering Gazebo, never both. `stop` takes the
mutex for another consumer and stops the neml-vllm container; `start` releases
it and brings vLLM back (~40 s). Manual control exists because a human running
a `visual` experiment at the bench needs the same lock the orchestrator uses.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from neml_brain.api import deps
from neml_brain.api.problem import Problem

router = APIRouter(prefix="/v1/runtime/llm", tags=["runtime"])


class GpuLockRequest(BaseModel):
    consumer: str = Field(
        min_length=1, description="Who holds the GPU: 'sim:visual', 'user:mg', 'agent:perception'."
    )
    timeout_s: float = Field(default=300.0, gt=0, le=3600)


@router.post("/stop")
async def stop_llm(body: GpuLockRequest, gpu_lock: deps.GpuLock) -> dict[str, Any]:
    """Acquire the GPU mutex for `consumer`; vLLM is stopped. Blocks up to
    `timeout_s` waiting for the current holder, then gives up with 409."""
    try:
        waited_s = await gpu_lock.acquire(body.consumer, timeout_s=body.timeout_s)
    except TimeoutError:
        raise Problem(
            409,
            "Conflict",
            f"GPU mutex still held after {body.timeout_s}s; vLLM was not stopped.",
            consumer=body.consumer,
        ) from None
    return {"llm": "stopped", "gpu_owner": body.consumer, "waited_s": waited_s}


@router.post("/start")
async def start_llm(body: GpuLockRequest, gpu_lock: deps.GpuLock) -> dict[str, Any]:
    """Release the GPU mutex held by `consumer` and start vLLM again. Releasing
    a lock you do not hold is a 409, not a silent no-op -- that bug would show
    up much later as two processes on one GPU."""
    try:
        released = await gpu_lock.release(body.consumer)
    except RuntimeError:
        released = False
    if released is False:
        raise Problem(
            409,
            "Conflict",
            f"'{body.consumer}' does not hold the GPU mutex.",
            consumer=body.consumer,
        )
    return {"llm": "starting", "gpu_owner": None}
