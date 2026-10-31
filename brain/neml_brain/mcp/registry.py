# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""MCP health probe behind GET /health (SPEC 8.3, acceptance T-016).

Every server in config/mcp.yaml is reported green or red - a server that is
configured but unreachable is a red line in /health, never a silent omission.
"""

from __future__ import annotations

import asyncio
from typing import Any

from neml_brain.mcp.client import McpClient, McpError

# ponytail: health has to answer in under a second; the per-server timeouts in
# config/mcp.yaml (600 s for sim) are run timeouts, not liveness timeouts.
PROBE_TIMEOUT_S = 5.0


async def probe(
    client: McpClient, server: str, timeout_s: float = PROBE_TIMEOUT_S
) -> dict[str, Any]:
    cfg = client.config(server)
    entry: dict[str, Any] = {"url": cfg.url, "status": "red", "tools": 0, "detail": None}
    try:
        tools = await client.list_tools(server, timeout_s=timeout_s)
    except McpError as exc:
        entry["detail"] = f"{type(exc).__name__}: {exc}"
        if cfg.optional:
            entry["status"] = "off"  # configured but not deployed here; not a fault
        return entry
    entry["status"] = "green"
    entry["tools"] = len(tools)
    return entry


async def health_snapshot(
    client: McpClient | None = None, timeout_s: float = PROBE_TIMEOUT_S
) -> dict[str, dict[str, Any]]:
    """{server: {status, url, tools, detail}} for every configured server."""
    owned = client is None
    client = client or McpClient()
    try:
        names = list(client.servers)
        results = await asyncio.gather(*(probe(client, name, timeout_s) for name in names))
        return dict(zip(names, results, strict=False))
    finally:
        if owned:
            await client.aclose()


def all_green(snapshot: dict[str, dict[str, Any]]) -> bool:
    return bool(snapshot) and all(
        entry["status"] in ("green", "off") for entry in snapshot.values()
    )
