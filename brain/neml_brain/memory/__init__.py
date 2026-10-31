# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Vector memory: chunking, CPU embeddings (SPEC 4.6) and pgvector search."""

from neml_brain.memory.chunking import chunk_text
from neml_brain.memory.consolidation import consolidate
from neml_brain.memory.embedding import EMBED_DIM, EMBED_MODEL, EmbeddingClient
from neml_brain.memory.store import Hit, insert_chunks, recall, search

__all__ = [
    "EMBED_DIM",
    "EMBED_MODEL",
    "EmbeddingClient",
    "Hit",
    "chunk_text",
    "consolidate",
    "insert_chunks",
    "recall",
    "search",
]
