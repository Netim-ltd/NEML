# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""pgvector reads and writes over memory_chunks (SPEC 7).

Cosine distance (`<=>`) against the HNSW index declared with vector_cosine_ops --
any other operator silently drops the index and turns the search into a seq scan.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from neml_brain.memory.embedding import EMBED_DIM, EmbeddingClient

DEFAULT_TOP_K = 8

_INSERT = text(
    """
    INSERT INTO memory_chunks (source_kind, source_id, content, embedding)
    VALUES (:source_kind, :source_id, :content, CAST(:embedding AS vector))
    """
)

_SEARCH = text(
    """
    SELECT id, source_kind, source_id, content,
           1 - (embedding <=> CAST(:query AS vector)) AS score
    FROM memory_chunks
    WHERE CAST(:kinds AS text[]) IS NULL OR source_kind = ANY(CAST(:kinds AS text[]))
    ORDER BY embedding <=> CAST(:query AS vector)
    LIMIT :top_k
    """
)


@dataclass(frozen=True)
class Hit:
    id: int
    source_kind: str
    source_id: str | None
    content: str
    score: float  # cosine similarity, 1.0 == identical


def vector_literal(embedding: Sequence[float]) -> str:
    """pgvector input format. Wrong length is caught here, not by the column."""
    if len(embedding) != EMBED_DIM:
        raise ValueError(f"memory_chunks.embedding is vector({EMBED_DIM}), got {len(embedding)}")
    return "[" + ",".join(repr(float(v)) for v in embedding) + "]"


async def insert_chunks(session: AsyncSession, rows: Sequence[Mapping[str, Any]]) -> int:
    """Write chunks. Each row: source_kind, source_id, content, embedding."""
    if not rows:
        return 0
    payload = [
        {
            "source_kind": row["source_kind"],
            "source_id": row.get("source_id"),
            "content": row["content"],
            "embedding": vector_literal(row["embedding"]),
        }
        for row in rows
    ]
    await session.execute(_INSERT, payload)
    return len(payload)


async def search(
    session: AsyncSession,
    embedding: Sequence[float],
    top_k: int = DEFAULT_TOP_K,
    source_kinds: Sequence[str] | None = None,
) -> list[Hit]:
    """Nearest neighbours by cosine distance over the HNSW index."""
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    result = await session.execute(
        _SEARCH,
        {
            "query": vector_literal(embedding),
            "kinds": list(source_kinds) if source_kinds else None,
            "top_k": top_k,
        },
    )
    return [
        Hit(
            id=row["id"],
            source_kind=row["source_kind"],
            source_id=row["source_id"],
            content=row["content"],
            score=float(row["score"]),
        )
        for row in result.mappings().all()
    ]


async def recall(
    session: AsyncSession,
    embedder: EmbeddingClient,
    query: str,
    top_k: int = DEFAULT_TOP_K,
    source_kinds: Sequence[str] | None = None,
) -> list[Hit]:
    """Embed a search string and return its neighbours. The agent read path."""
    embedding = (await embedder.embed([query], kind="query"))[0]
    return await search(session, embedding, top_k=top_k, source_kinds=source_kinds)
