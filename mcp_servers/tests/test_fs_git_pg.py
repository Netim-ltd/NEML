# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the three T-016 MCP servers (SPEC 6.1 #4/#5/#6, SPEC 6.2).

The rules each one exists to enforce, and therefore the only things worth
asserting: filesystem stays inside its two roots, git touches one repository,
postgres never writes.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from mcp_servers.neml_mcp_fs import server as fs
from mcp_servers.neml_mcp_git import server as git
from mcp_servers.neml_mcp_pg import server as pg

# --------------------------------------------------------------- filesystem


@pytest.fixture
def roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    (tmp_path / "outside").mkdir()
    monkeypatch.setenv("NEML_FS_ALLOWED_PATHS", str(work))
    return work


def test_read_write_round_trip_inside_a_root(roots: Path) -> None:
    written = fs.write_file(str(roots / "sub" / "a.txt"), "merhaba")
    assert written.size_bytes == len("merhaba")
    assert fs.read_file(str(roots / "sub" / "a.txt")) == "merhaba"
    assert [entry.name for entry in fs.list_dir(str(roots))] == ["sub"]
    assert fs.stat(str(roots / "sub")).kind == "dir"


def test_every_entry_point_refuses_a_path_outside_the_roots(roots: Path) -> None:
    outside = str(roots.parent / "outside" / "secret.txt")
    for call in (
        lambda: fs.read_file(outside),
        lambda: fs.write_file(outside, "x"),
        lambda: fs.list_dir(str(roots.parent / "outside")),
        lambda: fs.stat(outside),
    ):
        with pytest.raises(fs.PathNotAllowed):
            call()


def test_traversal_out_of_a_root_is_refused_after_resolution(roots: Path) -> None:
    with pytest.raises(fs.PathNotAllowed):
        fs.read_file(str(roots / ".." / "outside" / "secret.txt"))


def test_a_file_over_the_limit_is_refused_before_it_is_read(
    roots: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = roots / "big.bin"
    target.write_text("x" * 64, encoding="utf-8")
    monkeypatch.setattr(fs, "MAX_READ_BYTES", 8)
    with pytest.raises(fs.FileTooLarge):
        fs.read_file(str(target))


def test_default_roots_are_the_two_spec_6_5_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEML_FS_ALLOWED_PATHS", raising=False)
    assert fs.DEFAULT_ROOTS == ("/srv/neml/work", "/srv/neml/artifacts")


# ---------------------------------------------------------------------- git


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    env = {**os.environ, "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"), "HOME": str(tmp_path)}
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True, env=env)  # noqa: S603, S607
    (path / "seed.txt").write_text("seed\n", encoding="utf-8")
    monkeypatch.setenv("NEML_GIT_REPO", str(path))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    return path


def test_status_log_and_commit_use_the_configured_repo(repo: Path) -> None:
    assert asyncio.run(git.repository()) == str(repo)
    assert asyncio.run(git.status()) == ["?? seed.txt"]

    result = asyncio.run(git.commit("seed the work repo"))
    assert len(result.sha) == 40
    assert result.files == 1

    commits = asyncio.run(git.log())
    assert commits[0].subject == "seed the work repo"
    # SPEC 5.4: an agent commit must be distinguishable from a human one.
    assert commits[0].author == "neml-mcp-git"
    assert asyncio.run(git.status()) == []
    assert asyncio.run(git.show("HEAD", "seed.txt")) == "seed\n"


def test_an_empty_message_is_refused(repo: Path) -> None:
    with pytest.raises(git.GitError):
        asyncio.run(git.commit("   "))


def test_a_path_that_is_not_a_work_tree_is_a_typed_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEML_GIT_REPO", str(tmp_path / "nope"))
    with pytest.raises(git.RepoNotFound):
        asyncio.run(git.status())


# ----------------------------------------------------------------- postgres


class FakeConnection:
    """Records what the server sent, so the read-only guarantees are observable."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.executed: list[str] = []
        self.fetched: list[str] = []
        self.closed = False

    async def execute(self, query: str, *args: Any) -> str:
        self.executed.append(query)
        return "OK"

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        self.fetched.append(query)
        return list(self.rows)

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def connection(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeConnection]:
    conn = FakeConnection([{"id": "R01"}, {"id": "R02"}])
    monkeypatch.setenv("NEML_DB_URL_READONLY", "postgresql://neml_ro:pw@localhost:5432/neml_local")

    async def connect(dsn: str) -> FakeConnection:
        conn.executed.append(f"dsn:{dsn}")
        return conn

    pg.configure(connect)
    yield conn
    pg.configure(None)


def test_a_select_runs_inside_a_read_only_transaction(connection: FakeConnection) -> None:
    result = asyncio.run(pg.query("SELECT id FROM robots"))
    assert result.columns == ["id"]
    assert result.row_count == 2
    assert not result.truncated
    assert "BEGIN TRANSACTION READ ONLY" in connection.executed
    assert connection.closed


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE robots SET state = 'idle'",
        "DELETE FROM tasks",
        "INSERT INTO robots (id) VALUES ('R09')",
        "DROP TABLE approvals",
        "SELECT 1; DROP TABLE approvals",
    ],
)
def test_every_write_is_refused_before_it_reaches_the_database(
    connection: FakeConnection, sql: str
) -> None:
    with pytest.raises(pg.NotReadOnly):
        asyncio.run(pg.query(sql))
    assert connection.fetched == []


def test_the_limit_is_capped_and_truncation_is_reported(
    connection: FakeConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    asyncio.run(pg.query("SELECT id FROM robots", limit=10**9))
    assert f"LIMIT {pg.MAX_LIMIT + 1}" in connection.fetched[0]

    result = asyncio.run(pg.query("SELECT id FROM robots", limit=1))
    assert result.truncated
    assert result.row_count == 1


def test_a_missing_dsn_is_a_typed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEML_DB_URL_READONLY", raising=False)
    with pytest.raises(pg.NotConfigured):
        asyncio.run(pg.query("SELECT 1"))


def test_a_table_name_that_is_not_plain_is_refused(connection: FakeConnection) -> None:
    with pytest.raises(pg.PgError):
        asyncio.run(pg.columns("robots; DROP TABLE approvals"))


# ------------------------------------------------------- transport (SPEC 6.2)


@pytest.mark.parametrize(
    ("module", "expected"),
    [(fs, "neml-mcp-fs"), (git, "neml-mcp-git"), (pg, "neml-mcp-pg")],
)
def test_each_server_exposes_its_tools_over_streamable_http(module: Any, expected: str) -> None:
    from fastapi.testclient import TestClient

    with TestClient(module.app) as client:
        listed = client.post(
            "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        ).json()
        assert set(module.TOOLS) == {tool["name"] for tool in listed["result"]["tools"]}

        info = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "initialize"}).json()
        assert info["result"]["serverInfo"]["name"] == expected
