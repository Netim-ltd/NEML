# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""GET /health — liveness plus per-component status (SPEC 8.3, T-016)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter

from neml_brain import __version__
from neml_brain.api import deps
from neml_brain.api.metrics import BRIDGE_CONNECTED

router = APIRouter(tags=["health"])


async def _probe(name: str, coro: Any) -> tuple[str, dict[str, Any]]:
    try:
        return name, {"status": "ok", "detail": await coro}
    except Exception as exc:  # a component being down is data, not a 500
        return name, {"status": "down", "detail": f"{type(exc).__name__}: {exc}"}


@router.get("/health")
async def health(
    repo: deps.Repo, llm: deps.Llm, mcp: deps.Mcp, bridge: deps.Bridge, budget: deps.Budget
) -> dict[str, Any]:
    """Alive if this responds at all. `components` carries the real picture:
    every MCP server is listed by name (T-016 acceptance criterion)."""
    probes = await asyncio.gather(
        _probe("db", repo.ping()),
        _probe("llm", llm.ping()),
        _probe("mcp", mcp.health()),
        _probe("bridge", bridge.health()),
        _probe("budget", budget.snapshot()),
    )
    components = dict(probes)

    mcp_component = components["mcp"]
    mcp_detail = mcp_component.get("detail")
    if mcp_component["status"] == "ok" and isinstance(mcp_detail, dict):
        statuses = [entry.get("status") for entry in mcp_detail.values() if isinstance(entry, dict)]
        if statuses and not all(status == "green" for status in statuses):
            mcp_component["status"] = "down"

    bridge_component = components["bridge"]
    bridge_detail = bridge_component.get("detail")
    if bridge_component["status"] == "ok" and isinstance(bridge_detail, dict):
        if bridge_detail.get("connected") is False:
            bridge_component["status"] = "down"
    BRIDGE_CONNECTED.set(1 if bridge_component["status"] == "ok" else 0)

    degraded = [name for name, value in components.items() if value["status"] != "ok"]
    return {
        "status": "degraded" if degraded else "ok",
        "version": __version__,
        "degraded": degraded,
        "components": components,
    }
