# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Doubles for the memory tests: a recording session and a fake embed service.

The real path needs PostgreSQL + pgvector (testcontainers, marked integration).
These cover the SQL we build and the data we hand it.
"""

from __future__ import annotations

from typing import Any

import pytest

from neml_brain.memory.embedding import EMBED_DIM


class FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> FakeResult:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class FakeSession:
    """Records every statement and returns the queued rows."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[tuple[str, Any]] = []

    async def execute(self, statement: Any, params: Any = None) -> FakeResult:
        self.calls.append((str(statement), params))
        return FakeResult(self.rows)

    @property
    def last_sql(self) -> str:
        return self.calls[-1][0]

    @property
    def last_params(self) -> Any:
        return self.calls[-1][1]


class FakeEmbedder:
    """Returns deterministic 384-dim vectors and records what it was asked."""

    def __init__(self) -> None:
        self.seen: list[tuple[tuple[str, ...], str]] = []

    async def embed(self, texts, kind: str = "passage") -> list[list[float]]:
        self.seen.append((tuple(texts), kind))
        return [[float(i % 7) / 10.0] * EMBED_DIM for i, _ in enumerate(texts)]


@pytest.fixture
def session() -> FakeSession:
    return FakeSession()


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()
