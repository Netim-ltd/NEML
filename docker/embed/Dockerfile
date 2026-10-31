# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# neml-embed (SPEC 4.6). Two stages on purpose: torch and transformers are only
# needed to produce the ONNX file, so they stay in the builder and the runtime
# image ships onnxruntime + tokenizers only.
# Build context is the repository root (see docker/compose.yml).

FROM python:3.12-slim AS model
COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /usr/local/bin/uv
# CPU torch only - this box has 3 GB of VRAM and none of it is for embeddings.
RUN uv pip install --system --no-cache torch --index-url https://download.pytorch.org/whl/cpu \
    && uv pip install --system --no-cache "optimum[onnxruntime]" transformers
COPY docker/embed/prepare_model.py /tmp/prepare_model.py
RUN python /tmp/prepare_model.py /opt/neml/embed-model

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /usr/local/bin/uv
RUN uv pip install --system --no-cache fastapi "uvicorn[standard]" onnxruntime tokenizers numpy

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NEML_EMBED_MODEL_DIR=/opt/neml/embed-model \
    TOKENIZERS_PARALLELISM=false

COPY --from=model /opt/neml/embed-model /opt/neml/embed-model
COPY docker/embed/app.py docker/embed/benchmark.py /app/

RUN useradd --create-home --uid 1000 --user-group neml
USER neml:neml
WORKDIR /app

EXPOSE 8081
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8081"]
