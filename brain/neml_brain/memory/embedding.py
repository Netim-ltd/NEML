# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 4.6 embedding client -- the `neml-embed` CPU service on :8081.

The GPU is fully committed to vLLM (SPEC 4.1), so embeddings are an HTTP call to
an ONNX/int8 service, never a local model load. e5 models are asymmetric: stored
text gets the `passage:` prefix, a search string gets `query:`.
"""

from __future__ import annotations

from collections.abc import Sequence

import httpx

EMBED_MODEL = "intfloat/multilingual-e5-small"
EMBED_DIM = 384
DEFAULT_TIMEOUT_S = 30.0

_PREFIX = {"passage": "passage: ", "query": "query: "}


class EmbeddingClient:
    """Thin client for neml-embed. One instance per process is enough."""

    def __init__(
        self,
        base_url: str,
        client: httpx.AsyncClient | None = None,
        timeout: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._owned = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def embed(self, texts: Sequence[str], kind: str = "passage") -> list[list[float]]:
        """Embed a batch. `kind` is `passage` for stored text, `query` for a search."""
        if kind not in _PREFIX:
            raise ValueError(f"kind must be one of {sorted(_PREFIX)}, got {kind!r}")
        if not texts:
            return []
        payload = {"model": EMBED_MODEL, "inputs": [_PREFIX[kind] + t for t in texts]}
        response = await self._client.post(f"{self._base_url}/embed", json=payload)
        response.raise_for_status()
        vectors = response.json()["embeddings"]
        if len(vectors) != len(texts):
            raise ValueError(f"neml-embed returned {len(vectors)} vectors for {len(texts)} inputs")
        for vector in vectors:
            if len(vector) != EMBED_DIM:
                raise ValueError(
                    f"expected {EMBED_DIM}-dim vectors (SPEC 4.6), got {len(vector)}; "
                    "the column is vector(384) and will reject this"
                )
        return [[float(v) for v in vector] for vector in vectors]

    async def aclose(self) -> None:
        if self._owned:
            await self._client.aclose()
