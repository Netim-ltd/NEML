# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 4.6 embedding client against a mocked neml-embed service."""

from __future__ import annotations

import json

import httpx
import pytest

from neml_brain.memory.embedding import EMBED_DIM, EMBED_MODEL, EmbeddingClient


def _client(handler) -> EmbeddingClient:
    transport = httpx.MockTransport(handler)
    return EmbeddingClient("http://embed:8081", client=httpx.AsyncClient(transport=transport))


def _ok(dim: int = EMBED_DIM):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["payload"] = json.loads(request.content)
        count = len(seen["payload"]["inputs"])
        return httpx.Response(200, json={"embeddings": [[0.1] * dim for _ in range(count)]})

    return handler, seen


async def test_passage_and_query_prefixes_are_applied():
    handler, seen = _ok()
    client = _client(handler)
    await client.embed(["basamak hatasi"], kind="passage")
    assert seen["url"] == "http://embed:8081/embed"
    assert seen["payload"] == {"model": EMBED_MODEL, "inputs": ["passage: basamak hatasi"]}

    await client.embed(["basamak hatasi"], kind="query")
    assert seen["payload"]["inputs"] == ["query: basamak hatasi"]
    await client.aclose()


async def test_vectors_come_back_as_floats_of_the_right_width():
    handler, _ = _ok()
    vectors = await _client(handler).embed(["a", "b"])
    assert len(vectors) == 2
    assert all(len(v) == EMBED_DIM for v in vectors)
    assert all(isinstance(x, float) for x in vectors[0])


async def test_a_model_of_the_wrong_width_is_refused():
    handler, _ = _ok(dim=768)
    with pytest.raises(ValueError, match="384-dim"):
        await _client(handler).embed(["a"])


async def test_an_empty_batch_makes_no_request():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("neml-embed should not be called for an empty batch")

    assert await _client(handler).embed([]) == []


async def test_an_unknown_kind_is_refused():
    handler, _ = _ok()
    with pytest.raises(ValueError, match="kind must be"):
        await _client(handler).embed(["a"], kind="document")


async def test_a_service_error_propagates():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="model loading")

    with pytest.raises(httpx.HTTPStatusError):
        await _client(handler).embed(["a"])
