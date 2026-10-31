#!/usr/bin/env bash
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# NEML_SPEC.md 17.4 step 1 - Ubuntu 24.04 base packages, Docker, and the NVIDIA
# driver + container toolkit the vLLM container needs (SPEC 4.2).
# Idempotent: every step checks before it acts, so a second run is a no-op.
#
#   sudo scripts/setup/01_system.sh

set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }
. /etc/os-release
[[ "${VERSION_ID}" == "24.04" ]] || echo "WARNING: SPEC 2 fixes Ubuntu 24.04, this is ${VERSION_ID}"

TARGET_USER="${SUDO_USER:-root}"
export DEBIAN_FRONTEND=noninteractive

echo "== base packages =="
apt-get update -qq
apt-get install -y --no-install-recommends \
    build-essential git git-lfs curl wget ca-certificates gnupg jq unzip xz-utils \
    python3 python3-venv python3-dev pipx \
    postgresql-client libpq-dev \
    usbutils can-utils i2c-tools \
    htop tmux
git lfs install --system

echo "== uv (the project's Python installer) =="
if ! command -v uv >/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | UV_INSTALL_DIR=/usr/local/bin sh
fi
uv --version

echo "== docker engine + compose plugin =="
if [[ ! -f /etc/apt/keyrings/docker.asc ]]; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
fi
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
[[ "${TARGET_USER}" == "root" ]] || usermod -aG docker "${TARGET_USER}"

echo "== nvidia driver =="
# SPEC 4.1: 3 GB of VRAM is the whole AI budget, so the driver matters more than
# its version. ubuntu-drivers picks the recommended one for the installed card.
if ! command -v nvidia-smi >/dev/null; then
    apt-get install -y ubuntu-drivers-common
    ubuntu-drivers install || echo "WARNING: no NVIDIA card detected, or install failed"
else
    nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
fi

echo "== nvidia container toolkit (vLLM runs in docker) =="
if [[ ! -f /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg ]]; then
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
        | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
        | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
        > /etc/apt/sources.list.d/nvidia-container-toolkit.list
    apt-get update -qq
fi
apt-get install -y nvidia-container-toolkit
nvidia-ctk runtime configure --runtime=docker
systemctl restart docker

echo "== runtime directories (SPEC 17.3) =="
install -d -o "${TARGET_USER}" -g "${TARGET_USER}" /srv/neml/work /srv/neml/artifacts /srv/neml/config
install -d -o "${TARGET_USER}" -g "${TARGET_USER}" /var/lib/neml

echo
echo "01_system.sh done. Log out and back in for the docker group to apply."
echo "Next: sudo scripts/setup/02_ros2_jazzy.sh"
