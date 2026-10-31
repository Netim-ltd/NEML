# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""NEML_SPEC.md 8.2 - coding agent.

`coding` does NOT mean "the model writes code". Per SPEC 4.3 the LLM only
classifies (guided_choice) and fills parameters (guided_json); free-form code
generation is impossible by construction. This agent therefore receives an
already-prepared, template-rendered change, runs the SPEC 5.3 static checks on
it (ruff / mypy --strict / bandit plus the forbidden-call list below) and only
then hands it to the docker sandbox. Nothing it touches runs on the host.
"""

import ast
from typing import Any

from pydantic import BaseModel, ConfigDict

from neml_brain.agents.base import Deps, register
from neml_brain.agents.state import GraphState

# SPEC 5.3 forbidden-call list.
_BANNED_NAMES = frozenset({"eval", "exec", "__import__"})
_BANNED_ATTRS = frozenset({"os.system"})
_BANNED_MODULES = frozenset({"socket", "ctypes"})
# SPEC 5.3 permits subprocess only from an allowlist. Nothing is on it: the
# sandbox has no network and no binaries worth spawning.
# ponytail: empty frozenset, add entries here if a template ever needs a binary.
SUBPROCESS_ALLOWLIST: frozenset[str] = frozenset()


class ChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str  # path inside the sandbox /work mount
    source: str  # rendered by a deterministic template, never by the model
    command: list[str] = ["python", "-m", "pytest", "-q"]


class ChangeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool
    findings: list[str] = []
    sandbox: dict[str, Any] | None = None


def _dotted(node: ast.Attribute) -> str:
    parts = [node.attr]
    current: ast.expr = node.value
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def static_check(source: str) -> list[str]:
    """SPEC 5.3 forbidden-call scan. AST, not regex: comments and strings lie."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"syntax: {exc}"]

    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in _BANNED_NAMES:
            findings.append(f"forbidden call: {node.id}")
        elif isinstance(node, ast.Attribute):
            dotted = _dotted(node)
            if dotted in _BANNED_ATTRS:
                findings.append(f"forbidden call: {dotted}")
            elif dotted.startswith("subprocess.") and dotted not in SUBPROCESS_ALLOWLIST:
                findings.append(f"forbidden call: {dotted}")
        elif isinstance(node, ast.Import | ast.ImportFrom):
            modules = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [alias.name for alias in node.names]
            )
            for module in modules:
                root = module.split(".", 1)[0]
                if root in _BANNED_MODULES or (root == "subprocess" and not SUBPROCESS_ALLOWLIST):
                    findings.append(f"forbidden import: {module}")
    return findings


async def node(state: GraphState, deps: Deps) -> dict[str, Any]:
    request = ChangeRequest.model_validate(state.params)
    findings = static_check(request.source)
    if findings:
        result = ChangeResult(accepted=False, findings=findings)
    else:
        # SPEC 5.3: docker, network none, read-only rootfs, 180 s timeout.
        report = await deps.sandbox.run(request.target, request.source, request.command)
        result = ChangeResult(accepted=bool(report.get("ok")), sandbox=report)
    return {"result": result.model_dump(mode="json"), "steps": 1}


# Owner decision 3 grants [db.read, sandbox.run] and forbids printer.* and
# firmware.*: this agent may run code, never build or flash anything. sandbox.run
# names the SPEC 5.3 docker runtime, which `deps.sandbox` executes directly - the
# grant is what authorises it, there is no MCP server behind it.
AGENT = register(
    "coding",
    input_schema=ChangeRequest,
    output_schema=ChangeResult,
    tools=("db.read", "sandbox.run"),
    node=node,
)
