# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""One robot in one Gazebo world (NEML_SPEC.md SS11.1, T-034).

use_sim_time is true for every node here. SS11.2 rule 4 forbids wall-clock
logic, and the only way to keep that honest with real_time_factor 0 is to have
nothing in the graph reading the system clock.

neml_safety is deliberately NOT started in sim. There is no ATmega328P in an
SDF world, so the watchdog would see no heartbeat, latch within 150 ms and
block the run. The safety stack is exercised on hardware (T-074/T-075) and by
its own unit tests, which cover the latch logic directly.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, SetEnvironmentVariable
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import Command, LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare

CONTROLLERS = ("joint_state_broadcaster", "imu_sensor_broadcaster", "joint_trajectory_controller")


def generate_launch_description() -> LaunchDescription:
    namespace = LaunchConfiguration("namespace")
    world = LaunchConfiguration("world")
    params_file = LaunchConfiguration("params_file")

    robot_description = Command(
        [
            "xacro ",
            PathJoinSubstitution(
                [FindPackageShare("neml_description"), "urdf", "quadruped_v2.urdf.xacro"]
            ),
            " use_sim:=true",
        ]
    )

    def include(package, launch_file, arguments):
        return IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                PathJoinSubstitution([FindPackageShare(package), "launch", launch_file])
            ),
            launch_arguments=arguments.items(),
        )

    return LaunchDescription(
        [
            DeclareLaunchArgument("namespace", default_value="r01"),
            DeclareLaunchArgument(
                "world",
                default_value="flat",
                choices=["flat", "obstacle_low", "ramp_10deg", "rough_terrain", "maze"],
            ),
            DeclareLaunchArgument(
                "params_file",
                default_value=PathJoinSubstitution(
                    [FindPackageShare("neml_bringup"), "config", "robot.yaml"]
                ),
            ),
            DeclareLaunchArgument(
                "bridge_config", default_value="/srv/neml/config/gz_bridge.yaml"
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
            include("neml_sim", "gz_sim.launch.py", {"world": world}),
            include(
                "neml_sim",
                "gz_bridge.launch.py",
                {
                    "namespace": namespace,
                    "world": world,
                    "bridge_config": LaunchConfiguration("bridge_config"),
                },
            ),
            Node(
                package="robot_state_publisher",
                executable="robot_state_publisher",
                namespace=namespace,
                output="screen",
                parameters=[
                    {"robot_description": robot_description, "use_sim_time": True}
                ],
            ),
            # gz_ros2_control hosts the controller manager inside the Gazebo
            # process, so only the spawners are needed here.
            Node(
                package="ros_gz_sim",
                executable="create",
                output="screen",
                arguments=[
                    "-name", namespace,
                    "-topic", ["/", namespace, "/robot_description"],
                    "-z", "0.30",
                ],
                parameters=[{"use_sim_time": True}],
            ),
            *[
                Node(
                    package="controller_manager",
                    executable="spawner",
                    namespace=namespace,
                    arguments=[name, "--controller-manager", "controller_manager"],
                    output="screen",
                    parameters=[{"use_sim_time": True}],
                )
                for name in CONTROLLERS
            ],
            Node(
                package="neml_perception",
                executable="camera_gate",
                name="camera_gate",
                namespace=namespace,
                output="screen",
                parameters=[params_file, {"use_sim_time": True}],
            ),
        ]
    )
