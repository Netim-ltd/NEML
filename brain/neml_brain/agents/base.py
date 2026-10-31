# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# NEML_SPEC.md 8.2 / 5.4 - shared agent declaration.
#
# ponytail: one frozen dataclass plus register(), no base-class hierarchy.
# Eleven agents that differ only in a schema, a tool tuple and one function do
# not need inheritance. If an agent ever needs real behaviour of its own it
# gets its own module-level function, not a subclass.

from __future__ import annotations

import fnmatch
import hashlib
import json
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from functools import cache
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import BaseModel, ConfigDict

from neml_brain.llm.untrusted import wrap
from neml_brain.paths import CONFIG_DIR

if TYPE_CHECKING:  # pragma: no cover - runtime wiring lives in other modules
    from neml_brain.agents.state import GraphState

# SPEC 5.4 - the static tool policy. Not configurable: the whole point is that
# an agent's tool list cannot be widened at runtime.
POLICY_PATH = CONFIG_DIR / "policy" / "tools.yaml"


class ToolNotPermitted(RuntimeError):
    """SPEC 5.4 - the tool is outside the agent's static grant."""


class ApprovalRequired(RuntimeError):
    """SPEC 5.2 - the tool needs a decided human approval and has none."""


@dataclass(frozen=True, slots=True)
class Deps:
    """Everything a node may touch. Injected, so nothing here is a global.

    `llm` is a SPEC 4.7 LLMProvider, `mcp` an MCP client whose `call(tool,
    params)` resolves a logical tool name against config/mcp.yaml, `db` the
    brain's data access layer, `sandbox` the SPEC 5.3 docker runner, `bridge`
    the SPEC 9.5 cloud bridge that PERSIST publishes to, `gpu` the SPEC 4.5
    GpuLock the perception node holds while a visual sim renders.
    """

    llm: Any
    mcp: Any
    db: Any
    sandbox: Any = None
    bridge: Any = None
    gpu: Any = None


def untrusted(instruction: str, text: str, source: str = "user_message") -> str:
    """SPEC 5.4 - wrap untrusted text so it is data, never instruction.

    Delegates to llm.untrusted.wrap(): that is the one wrapper whose output the provider's
    check() accepts. A second hand-rolled block lacked its warning and every command failed.
    """
    return f"{instruction}\n\n{wrap(text, source).rstrip()}"


class DesignRequest(BaseModel):
    """Input to every SPEC 8.4 DESIGN-branch agent: the routed command.

    `command` is untrusted (SPEC 5.4) and only ever reaches the model inside an
    <untrusted_data> block.
    """

    model_config = ConfigDict(extra="forbid")

    command: str
    intent: str


@cache
def _policy() -> dict[str, Any]:
    return yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8")) or {}


def _forbidden(name: str) -> list[str]:
    policy = _policy()
    entry = (policy.get("agents") or {}).get(name) or {}
    return list(policy.get("global_forbidden") or []) + list(entry.get("forbidden") or [])


def grants(name: str) -> tuple[frozenset[str], frozenset[str]]:
    """(permitted, approval_gated) for `name` per config/policy/tools.yaml.

    An agent with no entry in tools.yaml is granted nothing. Deny by default:
    SPEC 5.4 says the list cannot be widened at runtime, and an absent list is
    an empty list, not a wildcard.
    """
    entry = (_policy().get("agents") or {}).get(name) or {}
    gated = frozenset(entry.get("requires_approval") or [])
    return frozenset(entry.get("tools") or []) | gated, gated


@dataclass(frozen=True, slots=True)
class Agent:
    """A SPEC 8.2 agent: declared schemas, a static tool grant, one node."""

    name: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    tools: tuple[str, ...] = ()
    gated: tuple[str, ...] = ()
    # SPEC 8.4 design-chain stage -> tool name. A missing stage is skipped.
    stages: Mapping[str, str] = field(default_factory=dict)
    node: Callable[[GraphState, Deps], Awaitable[dict[str, Any]]] | None = None

    async def call(
        self,
        deps: Deps,
        tool: str,
        params: dict[str, Any],
        approval_id: str | None = None,
    ) -> Any:
        """Deterministic MCP call. SPEC 6.5: the node picks the tool, never the model.

        Enforces the SPEC 5.4 grant and the SPEC 5.2 approval gate in code, then
        writes the SPEC 5.4 audit row (agent, tool, param hash, outcome,
        duration, approval reference).
        """
        if tool not in self.tools:
            await self._audit(deps, tool, params, "denied:not_permitted", 0, None)
            raise ToolNotPermitted(f"{self.name} may not call {tool}")
        if tool in self.gated and not approval_id:
            await self._audit(deps, tool, params, "denied:no_approval", 0, None)
            raise ApprovalRequired(f"{self.name}.{tool} requires a decided approval")

        started = time.monotonic()
        try:
            result = await deps.mcp.call(tool, params)
        except Exception as exc:
            outcome = f"error:{type(exc).__name__}"
            await self._audit(deps, tool, params, outcome, started, approval_id)
            raise
        await self._audit(deps, tool, params, "ok", started, approval_id)
        return result

    async def _audit(
        self,
        deps: Deps,
        tool: str,
        params: dict[str, Any],
        outcome: str,
        started: float,
        approval_id: str | None,
    ) -> None:
        # SPEC 5.4: parameters are hashed, never logged - they can carry
        # untrusted text and the audit log is kept for two years.
        await deps.db.audit(
            actor=f"agent:{self.name}",
            action=tool,
            target=self.name,
            params_hash=hashlib.sha256(
                json.dumps(params, sort_keys=True, default=str).encode()
            ).hexdigest(),
            outcome=outcome,
            duration_ms=int((time.monotonic() - started) * 1000) if started else 0,
            approval_id=approval_id,
        )


REGISTRY: dict[str, Agent] = {}


def register(
    name: str,
    *,
    input_schema: type[BaseModel],
    output_schema: type[BaseModel],
    tools: tuple[str, ...] = (),
    stages: Mapping[str, str] | None = None,
    node: Callable[[GraphState, Deps], Awaitable[dict[str, Any]]] | None = None,
) -> Agent:
    """Declare an agent and check its tool list against tools.yaml NOW.

    Construction time, not call time: a policy violation is an import error, so
    a bad grant can never reach production behind an untaken branch.
    """
    permitted, gated = grants(name)
    banned = _forbidden(name)
    for tool in tools:
        if any(fnmatch.fnmatch(tool, pattern) for pattern in banned):
            raise ToolNotPermitted(f"{name}: {tool} is forbidden by tools.yaml")
        if tool not in permitted:
            raise ToolNotPermitted(f"{name}: {tool} is not granted by tools.yaml")
    stages = dict(stages or {})
    for stage, tool in stages.items():
        if tool not in tools:
            raise ToolNotPermitted(f"{name}: stage {stage} uses undeclared tool {tool}")

    agent = Agent(
        name=name,
        input_schema=input_schema,
        output_schema=output_schema,
        tools=tuple(tools),
        gated=tuple(t for t in tools if t in gated),
        stages=stages,
        node=node,
    )
    REGISTRY[name] = agent
    return agent
