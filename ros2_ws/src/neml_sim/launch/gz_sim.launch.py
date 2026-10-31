# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Start Gazebo Harmonic headless on one of the five SS11.1 worlds.

    gz sim -s -r --headless-rendering <world>.sdf

-s  server only, no GUI process
-r  run immediately
--headless-rendering  camera sensors still render, there is just no window

There is no `gui` argument on purpose: SS11.1 says headless, and a human who
needs to watch a failure attaches to the running server with `gz sim -g`.

The physics numbers (DART, max_step_size 0.001, real_time_factor 0) live in the
world files, not here, so that the world sha256 in `sim_version` (SS11.2 rule 2)
covers them.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, SetEnvironmentVariable
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare

WORLDS = ("flat", "obstacle_low", "ramp_10deg", "rough_terrain", "maze")


def generate_launch_description() -> LaunchDescription:
    world = LaunchConfiguration("world")
    world_file = PathJoinSubstitution(
        [FindPackageShare("neml_sim"), "worlds", [world, ".sdf"]]
    )
    # gz resolves package:// against the directory that CONTAINS the package
    # share dir, hence the "..".
    share_root = PathJoinSubstitution([FindPackageShare("neml_description"), ".."])

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "world",
                default_value="flat",
                choices=list(WORLDS),
                description="One of the five SS11.1 worlds.",
            ),
            DeclareLaunchArgument(
                "verbosity", default_value="2", description="gz sim -v level."
            ),
            # SS17.2 network settings. Gazebo does not speak DDS itself, but
            # everything launched from here inherits the environment.
            SetEnvironmentVariable("ROS_DOMAIN_ID", "42"),
            SetEnvironmentVariable("RMW_IMPLEMENTATION", "rmw_zenoh_cpp"),
            SetEnvironmentVariable("GZ_SIM_RESOURCE_PATH", share_root),
            ExecuteProcess(
                cmd=[
                    "gz",
                    "sim",
                    "-s",
                    "-r",
                    "-v",
                    LaunchConfiguration("verbosity"),
                    "--headless-rendering",
                    world_file,
                ],
                output="screen",
            ),
        ]
    )
