# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
# neml-mcp-cad with FreeCAD (headless freecadcmd).

FROM debian:trixie-slim
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends freecad gmsh python3 python3-venv ca-certificates \
        libegl1 libgl1 libgl1-mesa-dri \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# The CAD server needs the MCP plumbing, and numpy/scipy for the finite-element solver (trixie's Python 3.13 is outside neml-brain's range).
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir fastapi "uvicorn[standard]" numpy scipy
COPY mcp_servers /app/mcp_servers

ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    QT_QPA_PLATFORM=offscreen HOME=/tmp NEML_ROOT=/app
RUN useradd --create-home --uid 1000 --user-group neml && mkdir -p /srv/neml/work /srv/neml/artifacts \
    && chown -R neml:neml /srv/neml /app
USER neml:neml
CMD ["uvicorn", "mcp_servers.neml_mcp_cad.server:app", "--host", "0.0.0.0", "--port", "9104"]
