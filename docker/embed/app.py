# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""neml-embed - the SPEC 4.6 embedding service on :8081.

The GPU belongs to vLLM (SPEC 4.1), so embeddings run on the CPU:
`intfloat/multilingual-e5-small` exported to ONNX and dynamically quantised to
int8 at image build time (docker/embed/prepare_model.py), 384 dimensions,
onnxruntime CPU provider.

The e5 family is asymmetric - stored text wants a `passage: ` prefix and a
search string wants `query: `. The caller adds that prefix
(brain/neml_brain/memory/embedding.py); this service embeds what it is given.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

MODEL_ID = "intfloat/multilingual-e5-small"
DIM = 384  # SPEC 4.6 / SPEC 7: the column is vector(384)
MAX_TOKENS = 512
MAX_BATCH = 256
MODEL_DIR = Path(os.environ.get("NEML_EMBED_MODEL_DIR", "/opt/neml/embed-model"))


def mean_pool(hidden: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Mean over real tokens only - padding must not move the vector."""
    weights = mask[:, :, None].astype(np.float32)
    return (hidden * weights).sum(axis=1) / np.clip(weights.sum(axis=1), 1e-9, None)


def l2_normalise(vectors: np.ndarray) -> np.ndarray:
    return vectors / np.clip(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12, None)


class Encoder:
    """One ONNX session. Thread count comes from OMP_NUM_THREADS (compose)."""

    def __init__(self, model_dir: Path = MODEL_DIR) -> None:
        # Imported here, not at module level: the tests and the pooling maths
        # run anywhere, only a real encoder needs the runtime wheels.
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self.tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=MAX_TOKENS)
        self.tokenizer.enable_padding()
        self.session = ort.InferenceSession(
            str(model_dir / "model_int8.onnx"), providers=["CPUExecutionProvider"]
        )
        self.input_names = [i.name for i in self.session.get_inputs()]

    def encode(self, texts: list[str]) -> list[list[float]]:
        encoded = self.tokenizer.encode_batch(texts)
        ids = np.array([e.ids for e in encoded], dtype=np.int64)
        mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
        feed: dict[str, np.ndarray] = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self.input_names:  # XLM-R exports ask for it, always zero
            feed["token_type_ids"] = np.zeros_like(ids)
        hidden = self.session.run(None, {k: v for k, v in feed.items() if k in self.input_names})[0]
        return l2_normalise(mean_pool(hidden, mask)).astype(np.float32).tolist()


_ENCODER: Encoder | None = None


def encoder() -> Encoder:
    """Loaded on first use so the container is up while ONNX warms."""
    global _ENCODER
    if _ENCODER is None:
        _ENCODER = Encoder()
    return _ENCODER


class EmbedRequest(BaseModel):
    """Both brain clients are accepted: one sends `texts`, the other `inputs`."""

    texts: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    model: str | None = None

    def items(self) -> list[str]:
        return self.texts or self.inputs


app = FastAPI(title="neml-embed", version="1.0.0", docs_url=None, redoc_url=None)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "model": MODEL_ID, "dim": DIM}


@app.post("/embed")
def embed(request: EmbedRequest) -> dict[str, Any]:
    texts = request.items()
    if not texts:
        return {"model": MODEL_ID, "dim": DIM, "embeddings": []}
    if len(texts) > MAX_BATCH:
        # Refused, not silently split: the caller decides how to chunk.
        raise HTTPException(422, f"batch of {len(texts)} exceeds {MAX_BATCH}")
    if request.model is not None and request.model != MODEL_ID:
        raise HTTPException(422, f"this service serves {MODEL_ID}, not {request.model!r}")
    return {"model": MODEL_ID, "dim": DIM, "embeddings": encoder().encode(texts)}
