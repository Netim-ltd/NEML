#!/usr/bin/env bash
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# NEML_SPEC.md 17.4 step 1 - Gazebo Harmonic and the ros_gz bridge (SPEC 11.1).
# Idempotent. Acceptance (T-002): `gz sim --versions` runs.
#
#   sudo scripts/setup/03_gazebo_harmonic.sh

set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }
. /etc/os-release
export DEBIAN_FRONTEND=noninteractive

echo "== osrf apt repository =="
if [[ ! -f /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg ]]; then
    apt-get update -qq
    apt-get install -y --no-install-recommends curl ca-certificates gnupg lsb-release
    curl -fsSL https://packages.osrfoundation.org/gazebo.gpg \
        -o /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/pkgs-osrf-archive-keyring.gpg] \
http://packages.osrfoundation.org/gazebo/ubuntu-stable ${VERSION_CODENAME} main" \
        > /etc/apt/sources.list.d/gazebo-stable.list
    apt-get update -qq
fi

echo "== gazebo harmonic + ros_gz bridge =="
apt-get install -y gz-harmonic ros-jazzy-ros-gz ros-jazzy-ros-gz-bridge ros-jazzy-ros-gz-sim

echo "== headless rendering (SPEC 4.5) =="
# The default sim profile is `fast`: no camera, CPU rendering, vLLM keeps the
# GPU. Only the `visual` profile takes the GPU, and then the orchestrator stops
# neml-vllm first. ogre2 without a display needs these.
apt-get install -y libogre-next-2.3-dev xvfb || true
cat > /etc/profile.d/neml-gz.sh <<'EOF'
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
# NEML_SPEC.md 11.1 / 4.5 - headless by default, DART physics, no wall clock.
export GZ_SIM_RESOURCE_PATH=/srv/neml/work/models:${GZ_SIM_RESOURCE_PATH:-}
export GZ_PARTITION=neml
EOF
chmod 0644 /etc/profile.d/neml-gz.sh

echo
echo "== verification (T-002) =="
gz sim --versions
echo "run a world headless with: gz sim -s -r --headless-rendering <world.sdf>"

echo
echo "03_gazebo_harmonic.sh done. Next: sudo scripts/setup/04_freecad_kicad_prusa.sh"
