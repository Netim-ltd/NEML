#!/usr/bin/env bash
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# NEML_SPEC.md 17.4 step 1 - ROS 2 Jazzy with the Zenoh middleware of SPEC 17.2.
# Idempotent. Acceptance (T-002): `ros2 doctor` is clean.
#
#   sudo scripts/setup/02_ros2_jazzy.sh

set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }
. /etc/os-release
export DEBIAN_FRONTEND=noninteractive

echo "== ros 2 apt repository =="
if [[ ! -f /usr/share/keyrings/ros-archive-keyring.gpg ]]; then
    apt-get update -qq
    apt-get install -y --no-install-recommends curl ca-certificates gnupg locales software-properties-common
    locale-gen en_US.UTF-8
    add-apt-repository -y universe
    curl -fsSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
        -o /usr/share/keyrings/ros-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] \
http://packages.ros.org/ros2/ubuntu ${VERSION_CODENAME} main" \
        > /etc/apt/sources.list.d/ros2.list
    apt-get update -qq
fi

echo "== ros 2 jazzy =="
# ros-base, not desktop: the lab box runs headless (SPEC 11.1) and rviz belongs
# on the operator's machine, not here.
apt-get install -y \
    ros-jazzy-ros-base ros-dev-tools \
    ros-jazzy-ros2-control ros-jazzy-ros2-controllers \
    ros-jazzy-xacro ros-jazzy-urdf ros-jazzy-robot-state-publisher \
    ros-jazzy-rmw-zenoh-cpp \
    ros-jazzy-launch-testing ros-jazzy-launch-testing-ros \
    python3-colcon-common-extensions python3-rosdep python3-vcstool

echo "== rosdep =="
[[ -f /etc/ros/rosdep/sources.list.d/20-default.list ]] || rosdep init
sudo -u "${SUDO_USER:-root}" rosdep update

echo "== environment (SPEC 17.2) =="
cat > /etc/profile.d/neml-ros.sh <<'EOF'
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
# NEML_SPEC.md 17.2 - every shell on this box talks on the same domain and RMW.
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=42
export RMW_IMPLEMENTATION=rmw_zenoh_cpp
export ZENOH_ROUTER_CONFIG_URI=/srv/neml/config/zenoh_router.json5
EOF
chmod 0644 /etc/profile.d/neml-ros.sh

if [[ ! -f /srv/neml/config/zenoh_router.json5 ]]; then
    echo "NOTE: /srv/neml/config/zenoh_router.json5 does not exist yet."
    echo "      Copy it from config/ in the repository (ROS 2 package work, T-034)."
fi

echo
echo "== verification (T-002) =="
# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash
ROS_DOMAIN_ID=42 RMW_IMPLEMENTATION=rmw_zenoh_cpp ros2 doctor || \
    echo "WARNING: ros2 doctor reported findings - T-002 is not met until it is clean"

echo
echo "02_ros2_jazzy.sh done. Next: sudo scripts/setup/03_gazebo_harmonic.sh"
