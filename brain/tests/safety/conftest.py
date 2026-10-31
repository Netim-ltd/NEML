# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""In-memory stand-in for the three tables the safety layer touches.

Keeps the unit tests off PostgreSQL; the real schema is exercised by the
@pytest.mark.integration tests and by the Alembic migration.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from neml_brain.runtime.audit import AuditLog


class FakeResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def scalar_one(self) -> Any:
        return self._rows[0][0]

    def one(self) -> tuple[Any, ...]:
        return self._rows[0]

    def first(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None


class FakeDb:
    def __init__(self) -> None:
        self.audit: list[dict[str, Any]] = []
        self.approvals: dict[str, dict[str, Any]] = {}
        self.safety_checks: list[tuple[bool, bool, bool, datetime]] = []
        self.commits = 0

    def execute(self, sql: str, params: dict[str, Any]) -> FakeResult:
        if sql.startswith("INSERT INTO audit_log"):
            self.audit.append(dict(params))
            return FakeResult([])
        if sql.startswith("INSERT INTO approvals"):
            new_id = str(uuid.uuid4())
            self.approvals[new_id] = {
                **params,
                "decision": None,
                "decided_by": None,
                "decided_at": None,
            }
            return FakeResult([(new_id,)])
        if sql.startswith("SELECT decision, decided_by, expires_at FROM approvals"):
            row = self.approvals[params["id"]]
            return FakeResult([(row["decision"], row["decided_by"], row["expires_at"])])
        if sql.startswith("UPDATE approvals"):
            row = self.approvals[params["id"]]
            if "AND decision IS NULL" not in sql or row["decision"] is None:
                row["decision"] = params["decision"]
                row["note"] = params["note"]
                row["decided_at"] = datetime.now(UTC)
            return FakeResult([])
        if sql.startswith("SELECT estop_ok"):
            return FakeResult(self.safety_checks[:1])
        raise AssertionError(f"unexpected statement: {sql}")

    def decide(self, approval_id: str, decision: str, decided_by: str) -> None:
        self.approvals[approval_id].update(decision=decision, decided_by=decided_by)


class FakeSession:
    def __init__(self, db: FakeDb) -> None:
        self._db = db

    async def execute(self, statement: Any, parameters: Any = None) -> FakeResult:
        return self._db.execute(" ".join(str(statement).split()), parameters or {})

    async def commit(self) -> None:
        self._db.commits += 1

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


@pytest.fixture
def db() -> FakeDb:
    return FakeDb()


@pytest.fixture
def session_factory(db: FakeDb) -> Any:
    return lambda: FakeSession(db)


@pytest.fixture
def audit(session_factory: Any) -> AuditLog:
    return AuditLog(session_factory)
