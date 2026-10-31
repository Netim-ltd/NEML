# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""pgvector reads and writes: the SQL and the payload we hand PostgreSQL."""

from __future__ import annotations

import pytest

from neml_brain.memory.embedding import EMBED_DIM
from neml_brain.memory.store import insert_chunks, recall, search, vector_literal

VECTOR = [0.5] * EMBED_DIM


def test_vector_literal_is_pgvector_syntax():
    literal = vector_literal([0.1, -0.25] + [0.0] * (EMBED_DIM - 2))
    assert literal.startswith("[0.1,-0.25,0.0")
    assert literal.endswith("]")
    assert literal.count(",") == EMBED_DIM - 1


def test_wrong_dimension_is_caught_before_the_database():
    with pytest.raises(ValueError, match="vector\\(384\\)"):
        vector_literal([0.1] * 128)


async def test_search_uses_the_cosine_operator_and_top_k(session):
    session.rows = [
        {
            "id": 1,
            "source_kind": "failure",
            "source_id": "task_run:7",
            "content": "tork",
            "score": 0.91,
        }
    ]
    hits = await search(session, VECTOR, top_k=5)

    sql = " ".join(session.last_sql.split())
    assert "embedding <=> CAST(:query AS vector)" in sql  # HNSW vector_cosine_ops
    assert "ORDER BY embedding <=> CAST(:query AS vector)" in sql
    assert session.last_params["top_k"] == 5
    assert session.last_params["kinds"] is None
    assert session.last_params["query"] == vector_literal(VECTOR)
    assert hits[0].source_id == "task_run:7"
    assert hits[0].score == pytest.approx(0.91)


async def test_search_can_filter_by_source_kind(session):
    await search(session, VECTOR, source_kinds=["failure", "doc"])
    assert session.last_params["kinds"] == ["failure", "doc"]
    assert "source_kind = ANY(CAST(:kinds AS text[]))" in " ".join(session.last_sql.split())


async def test_search_rejects_a_non_positive_top_k(session):
    with pytest.raises(ValueError, match="top_k"):
        await search(session, VECTOR, top_k=0)


async def test_insert_chunks_writes_one_row_per_chunk(session):
    rows = [
        {"source_kind": "failure", "source_id": "task_run:1", "content": "a", "embedding": VECTOR},
        {"source_kind": "note", "source_id": None, "content": "b", "embedding": VECTOR},
    ]
    assert await insert_chunks(session, rows) == 2
    assert "INSERT INTO memory_chunks" in session.last_sql
    assert session.last_params[0]["embedding"] == vector_literal(VECTOR)
    assert session.last_params[1]["source_id"] is None


async def test_insert_chunks_on_an_empty_batch_touches_nothing(session):
    assert await insert_chunks(session, []) == 0
    assert session.calls == []


async def test_recall_embeds_the_query_with_the_query_prefix(session, embedder):
    await recall(session, embedder, "basamak tirmanma hatasi", top_k=3)
    texts, kind = embedder.seen[-1]
    assert kind == "query"  # e5 is asymmetric: a search is not a passage
    assert texts == ("basamak tirmanma hatasi",)
    assert session.last_params["top_k"] == 3
