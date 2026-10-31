# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Service handles, taken from ``app.state`` (SPEC 8.2).

main.py's lifespan puts the real objects there; the contract tests put stubs
there. Routers never import the db/llm/mcp/agent packages directly, so the API
surface stays testable without a database, a GPU or an MCP daemon.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends
from starlette.requests import Request

from neml_brain.api.problem import Problem


def _from_state(name: str) -> Any:
    def dependency(request: Request) -> Any:
        service = getattr(request.app.state, name, None)
        if service is None:
            raise Problem(503, "Service Unavailable", f"'{name}' is not wired on this node.")
        return service

    return Depends(dependency)


# db/ — reads and writes over the SPEC 7 schema.
Repo = Annotated[Any, _from_state("repo")]
# agents/orchestrator.py — the SPEC 4.3 pipeline. The only LLM entry point.
Orchestrator = Annotated[Any, _from_state("orchestrator")]
# safety/ — deployment gates, approvals, software e-stop (SPEC 5.1/5.2).
Safety = Annotated[Any, _from_state("safety")]
# runtime/budget.py — SPEC 14.4 daily budgets.
Budget = Annotated[Any, _from_state("budget")]
# runtime/gpu_lock.py — SPEC 4.5 single GPU consumer.
GpuLock = Annotated[Any, _from_state("gpu_lock")]
# mcp/ — MCP client layer; health reports every server (T-016).
Mcp = Annotated[Any, _from_state("mcp")]
# mcp/ sim client — SPEC 6.3 neml-mcp-sim.
Sim = Annotated[Any, _from_state("sim")]
# bridge/ — WSS client to the .NET API (SPEC 9.5).
Bridge = Annotated[Any, _from_state("bridge")]
# llm/ — LLMProvider (SPEC 4.7).
Llm = Annotated[Any, _from_state("llm")]
