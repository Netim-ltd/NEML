# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Audit-log double: the runtime layer only ever inserts into audit_log."""

from __future__ import annotations

from typing import Any

import pytest

from neml_brain.runtime.audit import AuditLog


class FakeSession:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.commits = 0

    async def execute(self, statement: Any, parameters: Any = None) -> None:
        assert "INSERT INTO audit_log" in " ".join(str(statement).split())
        self._rows.append(dict(parameters or {}))

    async def commit(self) -> None:
        self.commits += 1

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


@pytest.fixture
def rows() -> list[dict[str, Any]]:
    return []


@pytest.fixture
def audit(rows: list[dict[str, Any]]) -> AuditLog:
    return AuditLog(lambda: FakeSession(rows))
