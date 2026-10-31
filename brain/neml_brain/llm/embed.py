# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SPEC 4.6 - client for the CPU embedding service `neml-embed` (:8081).

The service itself lives in docker/embed. Here we only call it and refuse
anything that is not a 384 dimension vector, because that is what the
PostgreSQL `vector(384)` column and the HNSW index expect (SPEC 7).
"""

import os

import httpx

DIM = 384
DEFAULT_URL = "http://localhost:8081"  # SPEC 17.1


async def embed(
    texts: list[str],
    url: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[list[float]]:
    """Embed `texts` and return one 384 dimension vector per input."""
    if not texts:
        return []
    base = (url or os.environ.get("NEML_EMBED_URL") or DEFAULT_URL).rstrip("/")
    own = client is None
    client = client or httpx.AsyncClient(timeout=30.0)
    try:
        response = await client.post(f"{base}/embed", json={"texts": list(texts)})
        response.raise_for_status()
        vectors: list[list[float]] = response.json()["embeddings"]
    finally:
        if own:
            await client.aclose()
    if len(vectors) != len(texts) or any(len(v) != DIM for v in vectors):
        raise ValueError(f"neml-embed answered off-contract; SPEC 4.6 requires {DIM} dimensions")
    return vectors
