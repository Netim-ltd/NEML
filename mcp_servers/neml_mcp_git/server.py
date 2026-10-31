# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""neml-mcp-git - git MCP server, port 9108 (SPEC 6.1 #6, T-016).

One repository, fixed at startup: /srv/neml/work/repo. Never the deployment
tree - an agent that could commit into this repo could change the code that
gates it (SPEC 5.4 `db.write_raw`, `safety.*` and `firmware.flash` are the same
class of rule). Every call is `git -C <repo>` as a separate process (SPEC 1.3).

The SPEC 6.2 fallback for the upstream stdio server, so `docker compose up`
alone makes /health green (T-016).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp_servers._common import make_app, run_cli

PORT = 9108
VERSION = "1.0.0"
DEFAULT_REPO = "/srv/neml/work/repo"
DEFAULT_TIMEOUT_S = 60.0
LOG_LIMIT = 50


class GitError(RuntimeError):
    """Base typed error; every entry point raises one of these (SPEC 6.3)."""


class RepoNotFound(GitError):
    """The configured path is not a git work tree."""


@dataclass
class Commit:
    sha: str
    author: str
    date: str
    subject: str


@dataclass
class CommitResult:
    sha: str
    files: int


def _repo() -> Path:
    """NEML_GIT_REPO overrides the work repo for tests and for a relocated lab."""
    return Path(os.environ.get("NEML_GIT_REPO", DEFAULT_REPO))


async def _git(*args: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> str:
    repo = _repo()
    if not (repo / ".git").exists():
        raise RepoNotFound(f"'{repo}' is not a git work tree")
    return await run_cli(["git", "-C", str(repo), *args], timeout_s)


async def status() -> list[str]:
    """Porcelain status of the work repo, one entry per changed path."""
    out = await _git("status", "--porcelain")
    return [line for line in out.splitlines() if line.strip()]


async def log(limit: int = LOG_LIMIT) -> list[Commit]:
    """Most recent commits, newest first."""
    out = await _git("log", f"-{max(1, min(limit, 500))}", "--pretty=format:%H%x1f%an%x1f%aI%x1f%s")
    commits = []
    for line in out.splitlines():
        if not line.strip():
            continue
        sha, author, date, subject = line.split("\x1f")
        commits.append(Commit(sha=sha, author=author, date=date, subject=subject))
    return commits


async def diff(ref: str = "HEAD") -> str:
    """Unified diff of the work tree against `ref`."""
    return await _git("diff", ref)


async def show(ref: str, path: str) -> str:
    """One file as of `ref`, without checking anything out."""
    return await _git("show", f"{ref}:{path}")


async def commit(message: str) -> CommitResult:
    """Stage everything in the work repo and commit it.

    The author is the daemon, not the operator: an agent commit must be
    distinguishable from a human one in `git log` without reading the message.
    """
    if not message.strip():
        raise GitError("a commit needs a message")
    await _git("add", "-A")
    await _git(
        "-c",
        "user.name=neml-mcp-git",
        "-c",
        "user.email=neml-mcp-git@localhost",
        "commit",
        "-m",
        message,
    )
    sha = (await _git("rev-parse", "HEAD")).strip()
    changed = await _git("show", "--name-only", "--pretty=format:", sha)
    return CommitResult(sha=sha, files=len([p for p in changed.splitlines() if p.strip()]))


async def repository() -> str:
    """The one repo this daemon will touch. An operator reads it from /health."""
    return str(_repo())


TOOLS: dict[str, Callable[..., Any]] = {
    "status": status,
    "log": log,
    "diff": diff,
    "show": show,
    "commit": commit,
    "repository": repository,
}

app = make_app("neml-mcp-git", VERSION, TOOLS)

if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT)
