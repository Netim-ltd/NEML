# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""neml-mcp-fs - filesystem MCP server, port 9107 (SPEC 6.1 #5, T-016).

SPEC 6.5 grants this server exactly two roots: /srv/neml/work and
/srv/neml/artifacts. Containment is checked here, on the resolved path, and
again in the client (brain/neml_brain/mcp/client.py `_check_paths`). Two checks
because the first one that fails is the one that matters, and a symlink out of
the sandbox only shows up after resolution.

SPEC 19 risk #4: the upstream `@modelcontextprotocol/server-filesystem` speaks
stdio and is installed by hand after a licence read (scripts/setup/05). This is
the SPEC 6.2 fallback the architecture plans for - our own server, Streamable
HTTP, in this tree, so `docker compose up` alone makes /health green (T-016).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp_servers._common import make_app

PORT = 9107
VERSION = "1.0.0"
# SPEC 6.5 config/mcp.yaml filesystem.allowed_paths - these two and nothing else.
DEFAULT_ROOTS = ("/srv/neml/work", "/srv/neml/artifacts")
MAX_READ_BYTES = 4 * 1024 * 1024  # a prompt cannot hold more than this anyway


class FsError(RuntimeError):
    """Base typed error; every entry point raises one of these (SPEC 6.3)."""


class PathNotAllowed(FsError):
    """Resolved path is outside every allowed root (SPEC 6.5)."""


class FileTooLarge(FsError):
    """Refused before the read, not after."""


@dataclass
class Entry:
    name: str
    path: str
    kind: str  # file | dir
    size_bytes: int


@dataclass
class WriteResult:
    path: str
    size_bytes: int


def _roots() -> tuple[Path, ...]:
    """NEML_FS_ALLOWED_PATHS overrides the roots for tests and for a relocated lab."""
    raw = os.environ.get("NEML_FS_ALLOWED_PATHS")
    values = raw.split(os.pathsep) if raw else DEFAULT_ROOTS
    return tuple(Path(value).resolve() for value in values if value)


def _resolve(path: str) -> Path:
    """The only way a path enters this module. Resolves first, then contains."""
    candidate = Path(path).resolve()
    for root in _roots():
        if candidate == root or root in candidate.parents:
            return candidate
    raise PathNotAllowed(f"'{path}' is outside {[str(r) for r in _roots()]}")


def _entry(path: Path) -> Entry:
    stat = path.stat()
    return Entry(
        name=path.name,
        path=str(path),
        kind="dir" if path.is_dir() else "file",
        size_bytes=0 if path.is_dir() else stat.st_size,
    )


def list_dir(path: str) -> list[Entry]:
    """List one directory inside an allowed root. Not recursive."""
    target = _resolve(path)
    if not target.is_dir():
        raise FsError(f"'{path}' is not a directory")
    return [_entry(child) for child in sorted(target.iterdir())]


def read_file(path: str) -> str:
    """Read a UTF-8 file inside an allowed root."""
    target = _resolve(path)
    if not target.is_file():
        raise FsError(f"'{path}' is not a file")
    size = target.stat().st_size
    if size > MAX_READ_BYTES:
        raise FileTooLarge(f"'{path}' is {size} bytes, limit is {MAX_READ_BYTES}")
    return target.read_text(encoding="utf-8", errors="replace")


def write_file(path: str, content: str) -> WriteResult:
    """Write a UTF-8 file inside an allowed root, creating parent directories."""
    target = _resolve(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    written = target.write_text(content, encoding="utf-8")
    return WriteResult(path=str(target), size_bytes=written)


def stat(path: str) -> Entry:
    """Existence, kind and size for one path inside an allowed root."""
    target = _resolve(path)
    if not target.exists():
        raise FsError(f"'{path}' does not exist")
    return _entry(target)


def allowed_paths() -> list[str]:
    """The roots this daemon will serve. /health and an operator both read it."""
    return [str(root) for root in _roots()]


TOOLS: dict[str, Callable[..., Any]] = {
    "list_dir": list_dir,
    "read_file": read_file,
    "write_file": write_file,
    "stat": stat,
    "allowed_paths": allowed_paths,
}

app = make_app("neml-mcp-fs", VERSION, TOOLS)

if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT)
