# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# NEML_SPEC.md 8.2 / 14.6 - memory agent. Turns a finished flow into
# memory_chunks rows (SPEC 7). Embedding and the pgvector write belong to
# neml_brain.memory and the PERSIST node; this agent only assembles content.

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from neml_brain.agents.base import Deps, register
from neml_brain.agents.state import GraphState

# ponytail: fixed-size split. Swap for neml_brain.memory.chunk() once the
# sentence-aware chunker exists; e5-small (384 dim) takes far less than this.
CHUNK_CHARS = 800


class MemoryWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: Literal["failure", "doc", "skill", "note"]
    source_id: str | None = None
    content: str


class Chunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: str
    source_id: str | None = None
    content: str


class MemoryChunks(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunks: list[Chunk] = []


def chunk(write: MemoryWrite) -> MemoryChunks:
    text = write.content.strip()
    pieces = [text[i : i + CHUNK_CHARS] for i in range(0, len(text), CHUNK_CHARS)]
    return MemoryChunks(
        chunks=[
            Chunk(source_kind=write.source_kind, source_id=write.source_id, content=piece)
            for piece in pieces
            if piece
        ]
    )


async def node(state: GraphState, deps: Deps) -> dict[str, Any]:
    write = MemoryWrite.model_validate(state.params)
    return {"result": chunk(write).model_dump(mode="json"), "steps": 1}


# Owner decision 3 grants the SPEC 4.6 / 14.6 step-3 path: read the run, embed
# the chunk on CPU, search and write memory_chunks. Chunking itself needs no
# tool, so the node below makes no call.
AGENT = register(
    "memory",
    input_schema=MemoryWrite,
    output_schema=MemoryChunks,
    tools=("db.read", "embed.encode", "memory.search", "memory.write"),
    node=node,
)
