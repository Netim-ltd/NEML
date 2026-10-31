# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for neml-embed (SPEC 4.6, T-006).

The real ONNX model only exists inside the image, so the session is faked here.
What is tested is what can break without it: the pooling maths, the 384
dimension contract, determinism, and both request shapes the brain uses.
"""

from __future__ import annotations

import hashlib

import numpy as np
import pytest
from fastapi.testclient import TestClient

import app as service


class FakeEncoder:
    """Deterministic 384-dim vectors derived from the text itself."""

    def encode(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
            vector = np.random.default_rng(seed).normal(size=service.DIM)
            out.append(service.l2_normalise(vector[None, :])[0].tolist())
        return out


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(service, "_ENCODER", FakeEncoder())
    return TestClient(service.app)


def test_mean_pool_ignores_padding() -> None:
    hidden = np.array([[[1.0, 1.0], [3.0, 3.0], [99.0, 99.0]]])
    mask = np.array([[1, 1, 0]])
    assert service.mean_pool(hidden, mask).tolist() == [[2.0, 2.0]]


def test_l2_normalise_gives_unit_vectors() -> None:
    norms = np.linalg.norm(service.l2_normalise(np.array([[3.0, 4.0], [0.0, 2.0]])), axis=1)
    assert np.allclose(norms, 1.0)


def test_embed_returns_384_dimensions(client: TestClient) -> None:
    response = client.post("/embed", json={"texts": ["passage: bir test parcasi"]})
    assert response.status_code == 200
    body = response.json()
    assert body["dim"] == service.DIM == 384
    assert [len(v) for v in body["embeddings"]] == [384]


def test_embed_is_deterministic(client: TestClient) -> None:
    payload = {"texts": ["query: ayni girdi", "passage: ayni girdi degil"]}
    first = client.post("/embed", json=payload).json()["embeddings"]
    second = client.post("/embed", json=payload).json()["embeddings"]
    assert first == second
    assert first[0] != first[1]


def test_accepts_the_inputs_key_too(client: TestClient) -> None:
    """brain/neml_brain/memory/embedding.py sends `inputs` + `model`."""
    response = client.post(
        "/embed", json={"model": service.MODEL_ID, "inputs": ["passage: iki istemci, tek servis"]}
    )
    assert response.status_code == 200
    assert len(response.json()["embeddings"][0]) == 384


def test_rejects_another_model(client: TestClient) -> None:
    response = client.post("/embed", json={"model": "some/other-model", "texts": ["x"]})
    assert response.status_code == 422


def test_rejects_oversized_batch(client: TestClient) -> None:
    response = client.post("/embed", json={"texts": ["x"] * (service.MAX_BATCH + 1)})
    assert response.status_code == 422


def test_empty_batch_is_not_an_error(client: TestClient) -> None:
    assert client.post("/embed", json={"texts": []}).json()["embeddings"] == []


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {
        "status": "ok",
        "model": "intfloat/multilingual-e5-small",
        "dim": 384,
    }
