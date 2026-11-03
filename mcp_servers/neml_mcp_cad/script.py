# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Parts written as build123d Python scripts (Open CASCADE), run in a separate, limited process.

The model writes a short script that leaves its part in a variable called `result`; the server builds it and exports STL + STEP and
returns the same measurements `build_recipe` does (volume_mm3, bbox, center_of_mass), so the judges and the benchmark read both alike.

Running a model's code is the risk, so it is narrowed in layers: the source is parsed first and refused unless it only imports
`build123d` / `math` and touches no file, process, network or dunder name; it then runs in its own interpreter (`python -I`) with a
memory, CPU-time and file-size limit, a clean environment and a temporary working directory, and is killed at the timeout.
# ponytail: a syntax allowlist plus rlimits, not a kernel sandbox; the container is the outer wall (non-root, no secrets mounted)."""

from __future__ import annotations

import ast
import asyncio
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

MAX_CHARS = 20000
TIMEOUT_S = 60.0
MEMORY_B = 3 * 1024**3
ALLOWED_IMPORTS = {"build123d", "math"}
BANNED_NAMES = {
    "exec", "eval", "open", "compile", "__import__", "globals", "locals", "vars", "getattr", "setattr", "delattr",
    "input", "breakpoint", "exit", "quit", "help", "memoryview", "os", "sys", "subprocess", "socket", "importlib",
}

_RUNNER = r"""
import json, sys
from build123d import *
req = json.load(open(sys.argv[1]))
ns = {"__name__": "part"}
exec("from build123d import *\nimport math", ns)
exec(compile(open(req["script"]).read(), "part.py", "exec"), ns)
r = ns.get("result")
r = getattr(r, "part", r)
if r is None:
    raise SystemExit("betik 'result' değişkenini tanımlamadı")
solids = list(r.solids())
if not solids:
    raise SystemExit("result katı bir gövde değil (solid yok)")
out = req["out"]
export_stl(r, out + ".stl", tolerance=0.05, angular_tolerance=0.3)
export_step(r, out + ".step")
bb = r.bounding_box()
c = r.center()
print("@@" + json.dumps({
    "volume_mm3": r.volume,
    "bbox": [bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z],
    "center_of_mass": [c.X, c.Y, c.Z],
    "solids": len(solids),
    "valid": bool(r.is_valid),
    "area_mm2": r.area,
    "stl": out + ".stl",
    "step": out + ".step",
}))
"""


class ScriptError(ValueError):
    """The script was refused or failed; the message is what the model reads to fix it."""


def check_script(src: str) -> None:
    """Refuse anything but plain build123d geometry code."""
    if not isinstance(src, str) or not src.strip():
        raise ScriptError("betik boş")
    if len(src) > MAX_CHARS:
        raise ScriptError(f"betik {MAX_CHARS} karakterden uzun")
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        raise ScriptError(f"sözdizimi hatası, satır {exc.lineno}: {exc.msg}") from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in ALLOWED_IMPORTS:
                    raise ScriptError(f"import yasak: {a.name} (yalnızca build123d ve math)")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] not in ALLOWED_IMPORTS or node.level:
                raise ScriptError(f"import yasak: {node.module} (yalnızca build123d ve math)")
        elif isinstance(node, ast.Name) and (node.id in BANNED_NAMES or (node.id.startswith("__") and node.id.endswith("__"))):
            raise ScriptError(f"yasak ad: {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise ScriptError(f"alt çizgiyle başlayan öznitelik yasak: .{node.attr}")


def _limits() -> None:  # runs in the child between fork and exec
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_B, MEMORY_B))
    resource.setrlimit(resource.RLIMIT_CPU, (int(TIMEOUT_S) + 5, int(TIMEOUT_S) + 5))
    resource.setrlimit(resource.RLIMIT_FSIZE, (200 * 1024**2, 200 * 1024**2))
    os.setsid()


async def run_script(source: str, out_dir: str, name: str, timeout_s: float = TIMEOUT_S, under: Any = None) -> dict[str, Any]:
    """Build the part a build123d script describes; returns volume_mm3, bbox, center_of_mass and the STL/STEP paths."""
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name):
        raise ScriptError("name must be lowercase letters, digits and underscores")
    check_script(source)
    out = (under(out_dir) if under else Path(out_dir)).resolve()
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        script, request = Path(tmp) / "part.py", Path(tmp) / "request.json"
        script.write_text(source, encoding="utf-8")
        request.write_text(json.dumps({"script": str(script), "out": str(out / name)}), encoding="utf-8")
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-c", _RUNNER, str(request),
            cwd=tmp, env={"PATH": os.environ.get("PATH", ""), "HOME": tmp, "OMP_NUM_THREADS": "2"},
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, preexec_fn=_limits,  # noqa: PLW1509 - rlimits must be set in the child
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), min(timeout_s, TIMEOUT_S))
        except TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise ScriptError(f"betik {min(timeout_s, TIMEOUT_S):.0f} sn içinde bitmedi (döngü ya da çok ağır işlem)") from exc
    text = stdout.decode("utf-8", "replace")
    line = next((ln for ln in reversed(text.splitlines()) if ln.startswith("@@")), None)
    if proc.returncode != 0 or line is None:
        err = stderr.decode("utf-8", "replace").strip().splitlines()
        raise ScriptError("betik çalışmadı: " + " | ".join(err[-3:])[:400] if err else "betik çalışmadı")
    result: dict[str, Any] = json.loads(line[2:])
    if not result["valid"]:
        raise ScriptError("sonuç geçersiz bir geometri (kendini kesiyor ya da açık yüzey)")
    return result
