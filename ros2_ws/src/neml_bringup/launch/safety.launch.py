# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Safety stack only (NEML_SPEC.md SS5.1, T-074).

Started on its own by robot.launch.py and startable on its own for the
pre-session e-stop and watchdog test. It has no dependency on the brain, on the
controllers, or on the network: if everything else is down, this still runs and
still reports.

respawn is on. A safety monitor that dies silently is worse than one that
restarts, because a restart re-latches and demands an operator - which is the
correct behaviour after an unexplained crash.

None of this replaces the L0 relay. See ros2_ws/src/neml_safety/README.md.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, SetEnvironmentVariable
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description() -> LaunchDescription:
    namespace = LaunchConfiguration("namespace")
    params_file = LaunchConfiguration("params_file")
    use_sim_time = LaunchConfiguration("use_sim_time")

    return LaunchDescription(
        [
            DeclareLaunchArgument("namespace", default_value="r01"),
            DeclareLaunchArgument(
                "params_file",
                default_value=PathJoinSubstitution(
                    [FindPackageShare("neml_bringup"), "config", "robot.yaml"]
                ),
            ),
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            DeclareLaunchArgument(
                "respawn",
                default_value="true",
                description="false only for launch tests, which need a clean exit.",
            ),
            DeclareLaunchArgument(
                "zenoh_config",
                default_value="/srv/neml/config/zenoh_router.json5",
                description="SS17.2 deploy path; source lives in this package.",
            ),
            # SS17.2
            SetEnvironmentVariable("ROS_DOMAIN_ID", "42"),
            SetEnvironmentVariable("RMW_IMPLEMENTATION", "rmw_zenoh_cpp"),
            SetEnvironmentVariable(
                "ZENOH_ROUTER_CONFIG_URI", LaunchConfiguration("zenoh_config")
            ),
            Node(
                package="neml_safety",
                executable="watchdog_monitor",
                name="watchdog_monitor",
                namespace=namespace,
                output="screen",
                emulate_tty=True,
                respawn=LaunchConfiguration("respawn"),
                respawn_delay=0.5,
                parameters=[params_file, {"use_sim_time": use_sim_time}],
            ),
        ]
    )
