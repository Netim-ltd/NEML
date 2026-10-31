# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""neml-mcp-pg - read-only PostgreSQL MCP server, port 9106 (SPEC 6.1 #4, T-016).

SPEC 6.1 #4 says READ-ONLY, no exceptions, and SPEC 5.4 forbids `db.write_raw`
outright. Read-only is enforced three times over, because one of them will be
the one that holds:

1. the connection string is the `neml_ro` role, whose GRANTs are SELECT only
   (mcp_servers/vendor/servers.yaml `required_grants`);
2. every statement runs inside `BEGIN TRANSACTION READ ONLY`, so the server
   rejects a write even if the role were widened by accident;
3. `_read_only()` below refuses anything that is not a single SELECT or WITH,
   so a write never reaches the database at all.

The SPEC 6.2 fallback for the upstream server, so `docker compose up` alone
makes /health green (T-016).
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from mcp_servers._common import make_app

PORT = 9106
VERSION = "1.0.0"
DEFAULT_LIMIT = 200
MAX_LIMIT = 5000
# One statement, and it reads. A trailing semicolon is allowed; a second is not.
_READ_ONLY = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)


class PgError(RuntimeError):
    """Base typed error; every entry point raises one of these (SPEC 6.3)."""


class NotReadOnly(PgError):
    """SPEC 6.1 #4 / SPEC 5.4: this server never writes."""


class NotConfigured(PgError):
    """No read-only DSN in the environment."""


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool


class Connection(Protocol):
    """The slice of an asyncpg connection this server uses."""

    async def fetch(self, query: str, *args: Any) -> list[Any]: ...

    async def execute(self, query: str, *args: Any) -> Any: ...

    async def close(self) -> None: ...


class Connector(Protocol):
    async def __call__(self, dsn: str) -> Connection: ...


_connect: Connector | None = None


def configure(connect: Connector | None) -> None:
    """Inject the connector. Tests pass a fake; production leaves it None and
    the asyncpg import happens on the first query."""
    global _connect
    _connect = connect


def _dsn() -> str:
    """SPEC 5.4: the secret lives in the process environment, never in config."""
    dsn = os.environ.get("NEML_DB_URL_READONLY")
    if not dsn:
        raise NotConfigured("NEML_DB_URL_READONLY is not set; this server reads nothing without it")
    # SPEC 17.3 writes the brain's URL with the SQLAlchemy driver suffix; asyncpg
    # takes a bare postgresql:// DSN.
    return dsn.replace("postgresql+asyncpg://", "postgresql://")


def _check_read_only(sql: str) -> str:
    statement = sql.strip().rstrip(";").strip()
    if not _READ_ONLY.match(statement):
        raise NotReadOnly("only SELECT and WITH statements are accepted")
    if ";" in statement:
        raise NotReadOnly("one statement per call")
    return statement


async def _open() -> Connection:
    if _connect is not None:
        return await _connect(_dsn())
    import asyncpg  # imported lazily: the module must import without a database

    connection: Connection = await asyncpg.connect(_dsn())
    return connection


async def _fetch(sql: str, limit: int, *args: Any) -> QueryResult:
    """`limit` is clamped by the caller; everything else is a bound parameter."""
    connection = await _open()
    try:
        # Layer 2: the transaction itself refuses a write.
        await connection.execute("BEGIN TRANSACTION READ ONLY")
        records = await connection.fetch(f"{sql} LIMIT {limit + 1}", *args)
    finally:
        await connection.close()
    truncated = len(records) > limit
    rows = [dict(record) for record in records[:limit]]
    columns = list(rows[0].keys()) if rows else []
    return QueryResult(columns=columns, rows=rows, row_count=len(rows), truncated=truncated)


async def query(sql: str, limit: int = DEFAULT_LIMIT) -> QueryResult:
    """Run one read-only statement and return its rows."""
    return await _fetch(_check_read_only(sql), max(1, min(limit, MAX_LIMIT)))


async def tables() -> QueryResult:
    """Every table in the public schema (SPEC 7)."""
    return await _fetch(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        " ORDER BY table_name",
        MAX_LIMIT,
    )


async def columns(table: str) -> QueryResult:
    """Column names and types of one public-schema table."""
    if not table.replace("_", "").isalnum():
        raise PgError(f"'{table}' is not a plain table name")
    # Bound parameter, not interpolation: the name check above is the second
    # line of defence, not the only one.
    return await _fetch(
        "SELECT column_name, data_type, is_nullable FROM information_schema.columns"
        " WHERE table_schema = 'public' AND table_name = $1 ORDER BY ordinal_position",
        MAX_LIMIT,
        table,
    )


TOOLS: dict[str, Callable[..., Any]] = {
    "query": query,
    "tables": tables,
    "columns": columns,
}

app = make_app("neml-mcp-pg", VERSION, TOOLS)

if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT)
