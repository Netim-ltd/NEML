# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Text chunking for memory_chunks (SPEC 7, SPEC 14.6).

Character windows with a small overlap, cut at the nearest line or word break so
a chunk never ends mid-token. multilingual-e5-small takes 512 tokens; ~800
characters of Turkish log text stays comfortably inside that.
"""

from __future__ import annotations

CHUNK_CHARS = 800
CHUNK_OVERLAP = 100


def chunk_text(text: str, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks. Empty input yields no chunks."""
    if size <= 0:
        raise ValueError("chunk size must be positive")
    if not 0 <= overlap < size:
        raise ValueError("overlap must be non-negative and smaller than the chunk size")

    body = text.strip()
    if not body:
        return []
    if len(body) <= size:
        return [body]

    chunks: list[str] = []
    start = 0
    while start < len(body):
        end = min(len(body), start + size)
        if end < len(body):
            floor = start + size // 2  # never cut in the first half of a chunk
            cut = max(body.rfind("\n", floor, end), body.rfind(" ", floor, end))
            if cut > floor:
                end = cut
        piece = body[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(body):
            break
        start = _next_start(body, start, end, overlap)
    return chunks


def _next_start(body: str, start: int, end: int, overlap: int) -> int:
    """Back off by the overlap, then snap forward so a chunk never opens mid-word."""
    nxt = max(end - overlap, start + 1)
    if body[nxt - 1].isspace():
        return nxt
    breaks = [i for i in (body.find(" ", nxt, end), body.find("\n", nxt, end)) if i != -1]
    return min(breaks) + 1 if breaks else end
