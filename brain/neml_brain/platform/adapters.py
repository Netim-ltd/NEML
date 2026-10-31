# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Explicit tool and environment ports with deterministic mock adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from neml_brain.mcp.client import McpClient
from neml_brain.platform.core import Scope


@dataclass(frozen=True)
class ToolCall:
    scope: Scope
    tool: str
    operation: str
    input_hash: str
    timeout_s: float


class McpAdapter(Protocol):
    async def invoke(self, call: ToolCall, arguments: dict[str, Any]) -> dict[str, Any]: ...


@dataclass
class MockMcpAdapter:
    name: str
    calls: list[ToolCall] = field(default_factory=list)

    async def invoke(self, call: ToolCall, arguments: dict[str, Any]) -> dict[str, Any]:
        if call.tool != self.name or call.timeout_s <= 0:
            raise ValueError("invalid tool call")
        self.calls.append(call)
        return {"tool": self.name, "operation": call.operation, "mock": True}


class ExistingMcpAdapter:
    """Connect platform operations to NEML's configured MCP client.

    Restrict operations at construction; arguments never choose another server.
    McpClient supplies transport timeouts, retries and configured path checks.
    """

    def __init__(self, client: McpClient, server: str, operations: frozenset[str]) -> None:
        self._client = client
        self._server = server
        self._operations = operations

    async def invoke(self, call: ToolCall, arguments: dict[str, Any]) -> dict[str, Any]:
        if call.tool != self._server or call.operation not in self._operations:
            raise PermissionError("MCP operation is not allowed")
        if call.timeout_s <= 0:
            raise ValueError("positive timeout required")
        result = await self._client.call(
            self._server, call.operation, arguments, timeout_s=call.timeout_s
        )
        return result if isinstance(result, dict) else {"result": result}


def media_adapters(client: McpClient) -> dict[str, ExistingMcpAdapter]:
    """FreeCAD remains source CAD; Blender is only a media consumer."""
    return {
        "freecad": ExistingMcpAdapter(
            client,
            "freecad",
            frozenset(
                {"build_recipe", "convert", "drawing", "standard_part", "fit", "assemble", "fem"}
            ),
        ),
        "kicad": ExistingMcpAdapter(
            client, "kicad", frozenset({"build_circuit", "run_drc", "run_erc", "export_bom"})
        ),
        "blender": ExistingMcpAdapter(
            client, "blender", frozenset({"render_photo", "render_video", "animate_assembly"})
        ),
    }


class SimulationEnvironment(Protocol):
    async def run(self, scope: Scope, scenario_id: str, model_version: str) -> dict[str, float]: ...


@dataclass
class MockGazeboEnvironment:
    scenarios: dict[str, dict[str, float]]

    async def run(self, scope: Scope, scenario_id: str, model_version: str) -> dict[str, float]:
        if not scope.tenant_id or not model_version:
            raise ValueError("scope and model required")
        return dict(self.scenarios[scenario_id])


EXAMPLE_SCENARIOS = {
    "home_person_nearby": {"success": 1.0, "safety_violation": 0.0},
    "field_obstacle": {"success": 1.0, "safety_violation": 0.0},
}
