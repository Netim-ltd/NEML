# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 5.3 code execution isolation.

Nothing the AI produces runs on the host. Static checks run first - the banned
call scan, then ruff, mypy --strict and bandit - and only code that passes all
of them reaches the container, which is started with exactly the SPEC 5.3
settings (no network, read-only rootfs, /work writable, 2 CPU, 2g, 256 pids,
180 s, uid 1000, all caps dropped, no-new-privileges).
"""

from __future__ import annotations

import ast
import asyncio
from collections.abc import Awaitable, Callable, Collection, Sequence
from dataclasses import dataclass, field
from pathlib import Path

IMAGE = "neml/sandbox:1.0"
TIMEOUT_S = 180.0
BANNED_CALLS = frozenset({"eval", "exec", "__import__"})
BANNED_MODULES = frozenset({"socket", "ctypes"})
# SPEC 1.3: GPL/AGPL tools are invoked as separate processes, so subprocess is not
# banned outright - only argv[0] outside this list is.
DEFAULT_SUBPROCESS_ALLOWLIST = frozenset(
    {"freecadcmd", "kicad-cli", "prusa-slicer", "prusa-gcodeviewer", "gz", "ros2"}
)


@dataclass(frozen=True, slots=True)
class RunResult:
    rc: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


Runner = Callable[[Sequence[str], float], Awaitable[RunResult]]


@dataclass(frozen=True, slots=True)
class SandboxResult:
    ok: bool
    stage: str  # banned_calls | ruff | mypy | bandit | container
    violations: tuple[str, ...] = ()
    run: RunResult | None = None


def _dotted(node: ast.expr) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _argv0(call: ast.Call) -> str | None:
    if not call.args:
        return None
    first = call.args[0]
    if isinstance(first, ast.List) and first.elts:
        first = first.elts[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value.split()[0] if first.value.split() else None
    return None


@dataclass
class _Scanner(ast.NodeVisitor):
    allowlist: Collection[str]
    violations: list[str] = field(default_factory=list)

    def _flag(self, node: ast.AST, what: str) -> None:
        self.violations.append(f"line {getattr(node, 'lineno', 0)}: {what}")

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name.split(".")[0] in BANNED_MODULES:
                self._flag(node, f"import {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        root = (node.module or "").split(".")[0]
        if root in BANNED_MODULES:
            self._flag(node, f"from {node.module} import ...")
        elif root == "subprocess":
            # An unqualified name defeats the argv[0] check below.
            self._flag(node, "from subprocess import ... (call subprocess.run instead)")
        elif root == "os" and any(a.name == "system" for a in node.names):
            self._flag(node, "from os import system")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _dotted(node.func)
        if name in BANNED_CALLS:
            self._flag(node, f"{name}()")
        elif name == "os.system":
            self._flag(node, "os.system()")
        elif name.startswith("subprocess."):
            if any(kw.arg == "shell" for kw in node.keywords):
                self._flag(node, f"{name}(shell=...)")
            argv0 = _argv0(node)
            if argv0 is None:
                self._flag(node, f"{name}() with a non-literal command")
            elif argv0 not in self.allowlist:
                self._flag(node, f"{name}() runs {argv0!r}, not in the allowlist")
        self.generic_visit(node)


def scan_banned_calls(
    source: str,
    *,
    allowlist: Collection[str] = DEFAULT_SUBPROCESS_ALLOWLIST,
    filename: str = "<generated>",
) -> list[str]:
    """SPEC 5.3 banned-call list, over the AST. Regex would miss aliasing and
    flag strings; the AST sees the real call shape.

    ponytail: defence in depth, not the boundary. Ceiling: getattr(os, 'system')
    style indirection is invisible here. The container is the real boundary;
    upgrade path is a seccomp profile if that ever stops being enough.
    """
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return [f"{filename}: does not parse: {exc}"]
    scanner = _Scanner(allowlist=allowlist)
    scanner.visit(tree)
    return [f"{filename}:{v}" for v in scanner.violations]


async def _subprocess_runner(argv: Sequence[str], timeout_s: float) -> RunResult:
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout_s)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return RunResult(124, "", f"timed out after {timeout_s}s", timed_out=True)
    return RunResult(
        proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
    )


class Sandbox:
    def __init__(
        self,
        runner: Runner | None = None,
        *,
        image: str = IMAGE,
        timeout_s: float = TIMEOUT_S,
        allowlist: Collection[str] = DEFAULT_SUBPROCESS_ALLOWLIST,
    ) -> None:
        self._runner = runner if runner is not None else _subprocess_runner
        self._image = image
        self._timeout_s = timeout_s
        self._allowlist = allowlist

    def docker_argv(self, work_dir: Path, argv: Sequence[str]) -> list[str]:
        """SPEC 5.3 yaml, one flag per setting."""
        return [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--volume",
            f"{work_dir}:/work",
            "--workdir",
            "/work",
            "--cpus",
            "2.0",
            "--memory",
            "2g",
            "--pids-limit",
            "256",
            "--user",
            "1000:1000",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            self._image,
            *argv,
        ]

    async def check(self, work_dir: Path) -> SandboxResult:
        """Static gate only. Returns the first failing stage."""
        violations = [
            v
            for path in sorted(work_dir.rglob("*.py"))
            for v in scan_banned_calls(
                path.read_text(encoding="utf-8"),
                allowlist=self._allowlist,
                filename=str(path.relative_to(work_dir)),
            )
        ]
        if violations:
            return SandboxResult(False, "banned_calls", tuple(violations))

        for stage, tool_argv in (
            ("ruff", ["ruff", "check", str(work_dir)]),
            ("mypy", ["mypy", "--strict", str(work_dir)]),
            ("bandit", ["bandit", "-q", "-r", str(work_dir)]),
        ):
            result = await self._runner(tool_argv, self._timeout_s)
            if result.rc != 0:
                return SandboxResult(False, stage, (result.stdout or result.stderr,), result)
        return SandboxResult(True, "static")

    async def run(self, work_dir: Path, argv: Sequence[str]) -> SandboxResult:
        static = await self.check(work_dir)
        if not static.ok:
            return static
        result = await self._runner(self.docker_argv(work_dir, argv), self._timeout_s)
        return SandboxResult(result.rc == 0 and not result.timed_out, "container", (), result)
