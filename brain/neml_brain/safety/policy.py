# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 5.4 static tool policy engine.

config/policy/tools.yaml is loaded once and frozen. An agent's tool list can
never be widened at runtime: there is no mutator on ToolPolicy and no override
argument on check(). global_forbidden outranks every agent entry.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from functools import cache
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from neml_brain.paths import CONFIG_DIR
from neml_brain.runtime.audit import AuditLog

DEFAULT_POLICY_PATH = CONFIG_DIR / "policy" / "tools.yaml"


class PolicyViolation(PermissionError):
    """Base for every refusal this engine raises. Never caught to 'try anyway'."""


class ToolForbidden(PolicyViolation):
    pass


class ApprovalRequired(PolicyViolation):
    pass


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    requires_approval: bool
    reason: str


@dataclass(frozen=True, slots=True)
class AgentRules:
    tools: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()
    requires_approval: tuple[str, ...] = ()


def _matches(patterns: Iterable[str], tool: str) -> bool:
    """Glob forms the config uses: printer.*, firmware.*, safety.* and literals."""
    return any(fnmatchcase(tool, p) for p in patterns)


@dataclass(frozen=True)
class ToolPolicy:
    agents: Mapping[str, AgentRules]
    global_forbidden: tuple[str, ...]

    def check(self, agent: str, tool: str) -> Decision:
        """Pure. Same inputs, same answer, no I/O, no state."""
        if _matches(self.global_forbidden, tool):
            return Decision(False, False, "global_forbidden")
        rules = self.agents.get(agent)
        if rules is None:
            return Decision(False, False, "unknown_agent")
        if _matches(rules.forbidden, tool):
            return Decision(False, False, "agent_forbidden")
        if _matches(rules.requires_approval, tool):
            return Decision(True, True, "requires_approval")
        if _matches(rules.tools, tool):
            return Decision(True, False, "allowed")
        return Decision(False, False, "not_in_tool_list")


def _rules(raw: Mapping[str, Any]) -> AgentRules:
    return AgentRules(
        tools=tuple(raw.get("tools") or ()),
        forbidden=tuple(raw.get("forbidden") or ()),
        requires_approval=tuple(raw.get("requires_approval") or ()),
    )


@cache
def load_policy(path: Path = DEFAULT_POLICY_PATH) -> ToolPolicy:
    """Load once, freeze. The cache is the 'cannot be widened at runtime' guarantee."""
    raw: Mapping[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    agents = {name: _rules(cfg or {}) for name, cfg in (raw.get("agents") or {}).items()}
    return ToolPolicy(
        agents=MappingProxyType(agents),
        global_forbidden=tuple(raw.get("global_forbidden") or ()),
    )


class PolicyEngine:
    """check() decides, authorize() decides *and* audits (SPEC 5.4, T-014)."""

    def __init__(self, audit: AuditLog, policy: ToolPolicy | None = None) -> None:
        self._policy = policy if policy is not None else load_policy()
        self._audit = audit

    def check(self, agent: str, tool: str) -> Decision:
        return self._policy.check(agent, tool)

    async def authorize(
        self,
        agent: str,
        tool: str,
        params: object | None = None,
        approval_id: str | None = None,
    ) -> Decision:
        started = time.monotonic()
        decision = self._policy.check(agent, tool)
        if not decision.allowed:
            outcome = f"denied:{decision.reason}"
        elif decision.requires_approval and approval_id is None:
            outcome = "denied:approval_missing"
        else:
            outcome = "allowed"
        await self._audit.write(
            actor=f"agent:{agent}",
            action=tool,
            target=None,
            params=params,
            outcome=outcome,
            duration_ms=int((time.monotonic() - started) * 1000),
            approval_id=approval_id,
        )
        if not decision.allowed:
            raise ToolForbidden(f"{agent} may not call {tool} ({decision.reason})")
        if decision.requires_approval and approval_id is None:
            raise ApprovalRequired(f"{tool} needs an approval row before {agent} may call it")
        return decision
