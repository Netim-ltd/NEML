# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""T-014: every agent/tool pair from SPEC 5.4, and the 100/100 refusal property."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from neml_brain.safety.policy import (
    ApprovalRequired,
    PolicyEngine,
    ToolForbidden,
    load_policy,
)

# SPEC 5.4 config/policy/tools.yaml, transcribed as a table.
ALLOWED = {
    "planner": {"db.read", "sim.read", "skill.read"},
    "mechanical": {"db.read", "cad.generate", "cad.export", "sim.run"},
    "manufacturing": {"db.read", "slicer.slice", "gcode.validate", "printer.status"},
    "electronics": {"db.read", "kicad.generate", "kicad.drc", "kicad.bom"},
}
NEEDS_APPROVAL = {
    "planner": set(),
    "mechanical": set(),
    "manufacturing": {"printer.start"},
    "electronics": {"kicad.gerber_export"},
}
# global_forbidden, expanded: firmware.flash, safety.* and db.write_raw.
GLOBAL_FORBIDDEN = {"firmware.flash", "safety.estop", "safety.watchdog", "db.write_raw"}
# Probes for the glob forms plus one unknown tool.
PROBES = {"printer.start", "printer.status", "firmware.build", "kicad.order", "shell.exec"}
ALL_TOOLS = sorted(
    set().union(*ALLOWED.values(), *NEEDS_APPROVAL.values(), GLOBAL_FORBIDDEN, PROBES)
)
PAIRS = [(agent, tool) for agent in ALLOWED for tool in ALL_TOOLS]


@pytest.fixture
def policy() -> Any:
    return load_policy()


@pytest.mark.parametrize(("agent", "tool"), PAIRS, ids=[f"{a}-{t}" for a, t in PAIRS])
def test_every_agent_tool_pair(policy: Any, agent: str, tool: str) -> None:
    decision = policy.check(agent, tool)
    if tool in GLOBAL_FORBIDDEN:
        assert not decision.allowed, "global_forbidden overrides everything"
        assert decision.reason == "global_forbidden"
    elif tool in NEEDS_APPROVAL[agent]:
        assert decision.allowed and decision.requires_approval
    elif tool in ALLOWED[agent]:
        assert decision.allowed and not decision.requires_approval
    else:
        assert not decision.allowed


@pytest.mark.parametrize(
    ("tool", "reason"),
    [
        ("printer.start", "agent_forbidden"),  # printer.*
        ("firmware.build", "agent_forbidden"),  # firmware.*
        ("firmware.flash", "global_forbidden"),  # global wins over agent
        ("kicad.order", "agent_forbidden"),
    ],
)
def test_mechanical_glob_forbidden(policy: Any, tool: str, reason: str) -> None:
    decision = policy.check("mechanical", tool)
    assert not decision.allowed
    assert decision.reason == reason


def test_unknown_agent_is_denied(policy: Any) -> None:
    assert policy.check("intruder", "db.read").reason == "unknown_agent"


def test_policy_is_loaded_once_and_frozen(policy: Any) -> None:
    assert load_policy() is policy
    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.global_forbidden = ()
    with pytest.raises(TypeError):  # MappingProxyType: no runtime widening
        policy.agents["planner"] = None


async def test_forbidden_call_refused_100_of_100_and_audited(audit: Any, db: Any) -> None:
    engine = PolicyEngine(audit)
    refused = 0
    for _ in range(100):
        try:
            await engine.authorize("mechanical", "printer.start", {"file": "x.gcode"})
        except ToolForbidden:
            refused += 1
    assert refused == 100
    assert len(db.audit) == 100
    assert {row["outcome"] for row in db.audit} == {"denied:agent_forbidden"}
    assert {row["actor"] for row in db.audit} == {"agent:mechanical"}


async def test_allowed_call_is_audited(audit: Any, db: Any) -> None:
    decision = await PolicyEngine(audit).authorize("planner", "db.read", {"q": "select 1"})
    assert decision.allowed
    assert db.audit[0]["outcome"] == "allowed"
    assert len(db.audit[0]["params_hash"]) == 64
    assert "select 1" not in str(db.audit[0])


async def test_requires_approval_without_row_is_refused(audit: Any, db: Any) -> None:
    engine = PolicyEngine(audit)
    with pytest.raises(ApprovalRequired):
        await engine.authorize("manufacturing", "printer.start", {"job": 1})
    assert db.audit[-1]["outcome"] == "denied:approval_missing"
    ok = await engine.authorize("manufacturing", "printer.start", {"job": 1}, approval_id="a-1")
    assert ok.requires_approval
    assert db.audit[-1]["approval_id"] == "a-1"
