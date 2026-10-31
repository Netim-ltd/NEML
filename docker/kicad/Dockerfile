# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /usr/local/bin/uv
RUN apt-get update \
    && apt-get install -y --no-install-recommends kicad ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY brain/pyproject.toml /app/brain/pyproject.toml
COPY brain/neml_brain /app/brain/neml_brain
RUN uv pip install --system --no-cache /app/brain
COPY mcp_servers /app/mcp_servers
COPY docker/brain/healthcheck.py /usr/local/bin/mcp_health.py
RUN useradd --create-home --uid 1000 --user-group neml \
    && mkdir -p /srv/neml/artifacts \
    && chown -R neml:neml /srv/neml /app
USER neml:neml
CMD ["uvicorn", "mcp_servers.neml_mcp_kicad.server:app", "--host", "0.0.0.0", "--port", "9105"]
