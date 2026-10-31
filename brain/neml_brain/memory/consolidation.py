# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 14.6 learning record, step 3 -- the routine idle policy step 5 calls.

Takes the last 24 hours of failure logs, chunks them, embeds them on CPU and
writes them to memory_chunks. Runs already consolidated are skipped in SQL, so
the idle loop can call this every time it finds nothing better to do.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from neml_brain.memory.chunking import chunk_text
from neml_brain.memory.embedding import EmbeddingClient
from neml_brain.memory.store import insert_chunks

WINDOW_H = 24  # SPEC 14.5 step 5.
SOURCE_KIND = "failure"
DEFAULT_LIMIT = 200

# SPEC 14.6 step 2 tags the failure mode; the tag is the most searchable part of
# the chunk, so it goes first.
_UNCONSOLIDATED = text(
    """
    SELECT tr.id, tr.env, tr.seed, tr.metrics, t.title, t.kind
    FROM task_runs tr
    JOIN tasks t ON t.id = tr.task_id
    WHERE tr.outcome = 'failure'
      AND tr.ended_at >= :since
      AND NOT EXISTS (
          SELECT 1 FROM memory_chunks m
          WHERE m.source_kind = :source_kind AND m.source_id = 'task_run:' || tr.id
      )
    ORDER BY tr.ended_at
    LIMIT :limit
    """
)


def failure_document(row: dict[str, Any]) -> str:
    """One failure run rendered as the text that gets embedded."""
    metrics = row.get("metrics") or {}
    tag = metrics.get("failure_tag", "untagged")
    lines = [
        f"failure_tag: {tag}",
        f"task: {row.get('title')} (kind={row.get('kind')})",
        f"env: {row.get('env')} seed: {row.get('seed')}",
    ]
    details = {k: v for k, v in metrics.items() if k != "failure_tag"}
    if details:
        lines.append("metrics: " + ", ".join(f"{k}={v}" for k, v in sorted(details.items())))
    return "\n".join(lines)


async def consolidate(
    session: AsyncSession,
    embedder: EmbeddingClient,
    window_h: int = WINDOW_H,
    now: datetime | None = None,
    limit: int = DEFAULT_LIMIT,
) -> int:
    """Chunk, embed and store the recent failure logs. Returns the chunks written."""
    since = (now or datetime.now(UTC)) - timedelta(hours=window_h)
    result = await session.execute(
        _UNCONSOLIDATED, {"since": since, "source_kind": SOURCE_KIND, "limit": limit}
    )
    runs = [dict(row) for row in result.mappings().all()]
    if not runs:
        return 0

    contents: list[str] = []
    source_ids: list[str] = []
    for run in runs:
        for chunk in chunk_text(failure_document(run)):
            contents.append(chunk)
            source_ids.append(f"task_run:{run['id']}")

    embeddings = await embedder.embed(contents)
    return await insert_chunks(
        session,
        [
            {
                "source_kind": SOURCE_KIND,
                "source_id": source_id,
                "content": content,
                "embedding": embedding,
            }
            for source_id, content, embedding in zip(source_ids, contents, embeddings, strict=True)
        ],
    )
