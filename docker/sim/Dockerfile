# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
# neml-mcp-sim with Gazebo Harmonic (headless, software GL) and the NemlSystem plugin.

FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends curl gnupg lsb-release ca-certificates \
        g++ cmake pkg-config nlohmann-json3-dev libssl-dev python3 python3-venv libegl1 libgl1-mesa-dri \
    && curl -fsSL https://packages.osrfoundation.org/gazebo.gpg -o /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/pkgs-osrf-archive-keyring.gpg] http://packages.osrfoundation.org/gazebo/ubuntu-stable $(lsb_release -cs) main" > /etc/apt/sources.list.d/gazebo-stable.list \
    && apt-get update && apt-get install -y --no-install-recommends gz-harmonic libgz-sim8-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY ros2_ws/src/neml_sim /app/ros2_ws/src/neml_sim
RUN mkdir -p /opt/neml/lib \
    && g++ -std=c++17 -O2 -fPIC -shared ros2_ws/src/neml_sim/src/NemlSystem.cc -o /opt/neml/lib/libNemlSystem.so \
        $(pkg-config --cflags --libs gz-sim8 gz-plugin2) -lssl -lcrypto

COPY brain/pyproject.toml /app/brain/pyproject.toml
COPY brain/neml_brain /app/brain/neml_brain
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir /app/brain
COPY mcp_servers /app/mcp_servers

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    GZ_SIM_SYSTEM_PLUGIN_PATH=/opt/neml/lib LIBGL_ALWAYS_SOFTWARE=1 NEML_ROOT=/app
RUN userdel -r ubuntu 2>/dev/null; useradd --create-home --uid 1000 --user-group neml && mkdir -p /srv/neml/work /srv/neml/artifacts \
    && chown -R neml:neml /srv/neml /app
USER neml:neml
CMD ["uvicorn", "mcp_servers.neml_mcp_sim.server:app", "--host", "0.0.0.0", "--port", "9101"]
