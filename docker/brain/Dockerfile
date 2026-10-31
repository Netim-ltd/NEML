# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# neml-brain (SPEC 8) plus the four MCP daemons of SPEC 6.2 - one image, five
# services, because they share every dependency and differ only in entry point.
# Build context is the repository root (see docker/compose.yml).

FROM python:3.12-slim

# uv is the project's installer (SPEC 2 toolchain); pinned to the 0.10 line.
COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    NEML_ROOT=/app \
    NEML_CONFIG_DIR=/app/config

WORKDIR /app

# Dependencies change far less often than the source, so install first.
COPY brain/pyproject.toml /app/brain/pyproject.toml
COPY brain/neml_brain /app/brain/neml_brain
COPY brain/alembic /app/brain/alembic
COPY brain/alembic.ini /app/brain/alembic.ini
COPY config /app/config
COPY hardware /app/hardware
RUN uv pip install --system --no-cache /app/brain

COPY mcp_servers /app/mcp_servers
COPY docker/brain/healthcheck.py /usr/local/bin/mcp_health.py

# SPEC 5.3 keeps generated code away from root; the daemons follow the same
# rule. The runtime directories are created here so a fresh named volume
# inherits this ownership instead of root's.
RUN useradd --create-home --uid 1000 --user-group neml \
    && mkdir -p /srv/neml/work /srv/neml/artifacts /var/lib/neml /app/config \
    && chown -R neml:neml /srv/neml /var/lib/neml /app

USER neml:neml

# Overridden per service in docker/compose.yml.
CMD ["uvicorn", "neml_brain.main:app", "--host", "0.0.0.0", "--port", "8080"]
