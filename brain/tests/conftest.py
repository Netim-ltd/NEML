# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Fixtures shared by every test directory (SPEC 18.1).

There is no database fixture here; the db tests stand testcontainers up in
their own conftest.
"""

from __future__ import annotations

import random
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import jsonschema
import pytest

SEED = 20260101
FROZEN_NOW = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)


@pytest.fixture
def rng() -> random.Random:
    """SPEC 11.2-1: every random draw derives from the one seed."""
    return random.Random(SEED)  # noqa: S311 - determinism, not cryptography


class FrozenClock:
    """Stopped clock. SPEC 11.2-4: logic never reads the wall clock, it is injected."""

    def __init__(self, start: datetime = FROZEN_NOW) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> datetime:
        self._now += timedelta(seconds=seconds)
        return self._now


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock()


@pytest.fixture
def artifact_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Throwaway NEML_ARTIFACT_DIR."""
    path = tmp_path / "artifacts"
    path.mkdir()
    monkeypatch.setenv("NEML_ARTIFACT_DIR", str(path))
    return path


class FakeLLM:
    """Fake provider that enforces the SPEC 4.3/4.7 contract.

    `classify` only ever returns one of the given options and `fill` output is
    validated against the schema: exactly like real guided decoding, output outside
    the schema is impossible. Free text comes only from `summarize` (shown to a human).
    """

    def __init__(
        self,
        choice: str | None = None,
        fill: dict[str, Any] | None = None,
        summary: str = "özet",
    ) -> None:
        self.choice = choice
        self.fill_value: dict[str, Any] = fill or {}
        self.summary_text = summary
        self.calls: list[tuple[str, str]] = []

    async def classify(self, prompt: str, choices: list[str]) -> str:
        self.calls.append(("classify", prompt))
        value = choices[0] if self.choice is None else self.choice
        if value not in choices:
            raise AssertionError(f"guided_choice ihlali: {value!r} seçenekler içinde değil")
        return value

    async def fill(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("fill", prompt))
        jsonschema.validate(self.fill_value, schema)
        return dict(self.fill_value)

    async def summarize(self, prompt: str, max_tokens: int) -> str:
        self.calls.append(("summarize", prompt))
        return self.summary_text[: max_tokens * 4]  # ponytail: ~4 characters per token, roughly


@pytest.fixture
def fake_llm() -> FakeLLM:
    """Tests script a scenario by setting `choice` / `fill_value` / `summary_text`."""
    return FakeLLM()


@pytest.fixture
async def client_factory() -> AsyncIterator[Callable[..., httpx.AsyncClient]]:
    """httpx client over an ASGI transport: no network, no server started."""
    clients: list[httpx.AsyncClient] = []

    def make(app: Any, **kwargs: Any) -> httpx.AsyncClient:
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://brain", **kwargs
        )
        clients.append(client)
        return client

    yield make
    for client in clients:
        await client.aclose()
