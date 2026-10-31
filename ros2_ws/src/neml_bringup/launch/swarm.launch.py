# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Lab-station swarm coordinator (NEML_SPEC.md Faz 5, T-082).

Runs on the lab station, not on a robot. It starts one coordinator for the
whole fleet; the per-robot link guard that reacts to losing it is started by
robot.launch.py.

Deliberately not respawned. If the coordinator dies, every robot's link guard
notices within 1.6 s and puts its robot into the latched safe state, which is
the behaviour T-083 asks for. Silently restarting the coordinator would race
that transition and could bring a robot back up without an operator.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, SetEnvironmentVariable
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description() -> LaunchDescription:
    params_file = LaunchConfiguration("params_file")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "params_file",
                default_value=PathJoinSubstitution(
                    [FindPackageShare("neml_bringup"), "config", "swarm.yaml"]
                ),
            ),
            DeclareLaunchArgument(
                "zenoh_config", default_value="/srv/neml/config/zenoh_router.json5"
            ),
            # SS17.2
            SetEnvironmentVariable("ROS_DOMAIN_ID", "42"),
            SetEnvironmentVariable("RMW_IMPLEMENTATION", "rmw_zenoh_cpp"),
            SetEnvironmentVariable(
                "ZENOH_ROUTER_CONFIG_URI", LaunchConfiguration("zenoh_config")
            ),
            Node(
                package="neml_swarm",
                executable="swarm_coordinator",
                name="swarm_coordinator",
                output="screen",
                emulate_tty=True,
                parameters=[params_file],
            ),
        ]
    )
