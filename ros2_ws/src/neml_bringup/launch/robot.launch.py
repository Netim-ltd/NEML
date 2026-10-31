# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Full stack on real hardware (NEML_SPEC.md Faz 4).

Order matters and is not cosmetic: the safety stack comes up first and latches,
so the controller manager can never be commanding joints before something is
watching the watchdog. The operator clears the latch with the reset service
after the SS5.1 pre-session self test.

The 1 kHz loop is NOT here. It runs on the STM32F446 (SS2); the controller
manager talks to it over micro-ROS topics through topic_based_ros2_control, and
runs at 1000 Hz itself so the setpoint cadence matches.

Not started here: the realsense driver and the micro-ROS agent. Both are
vendor processes with their own units and their own restart policy; the setup
scripts own them.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, SetEnvironmentVariable
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import Command, LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare

CONTROLLERS = ("joint_state_broadcaster", "imu_sensor_broadcaster", "joint_trajectory_controller")


def generate_launch_description() -> LaunchDescription:
    namespace = LaunchConfiguration("namespace")
    params_file = LaunchConfiguration("params_file")

    robot_description = Command(
        [
            "xacro ",
            PathJoinSubstitution(
                [FindPackageShare("neml_description"), "urdf", "quadruped_v2.urdf.xacro"]
            ),
            " use_sim:=false",
            " hw_topic_ns:=",
            namespace,
        ]
    )

    controller_spawners = [
        Node(
            package="controller_manager",
            executable="spawner",
            namespace=namespace,
            arguments=[name, "--controller-manager", "controller_manager"],
            output="screen",
        )
        for name in CONTROLLERS
    ]

    return LaunchDescription(
        [
            DeclareLaunchArgument("namespace", default_value="r01"),
            DeclareLaunchArgument(
                "params_file",
                default_value=PathJoinSubstitution(
                    [FindPackageShare("neml_bringup"), "config", "robot.yaml"]
                ),
            ),
            DeclareLaunchArgument(
                "zenoh_config", default_value="/srv/neml/config/zenoh_router.json5"
            ),
            DeclareLaunchArgument("enable_learning_feedback", default_value="false"),
            # SS17.2
            SetEnvironmentVariable("ROS_DOMAIN_ID", "42"),
            SetEnvironmentVariable("RMW_IMPLEMENTATION", "rmw_zenoh_cpp"),
            SetEnvironmentVariable(
                "ZENOH_ROUTER_CONFIG_URI", LaunchConfiguration("zenoh_config")
            ),
            # 1. safety first, latched
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    PathJoinSubstitution(
                        [FindPackageShare("neml_bringup"), "launch", "safety.launch.py"]
                    )
                ),
                launch_arguments={
                    "namespace": namespace,
                    "params_file": params_file,
                    "use_sim_time": "false",
                    "zenoh_config": LaunchConfiguration("zenoh_config"),
                }.items(),
            ),
            # 2. kinematics
            Node(
                package="robot_state_publisher",
                executable="robot_state_publisher",
                namespace=namespace,
                output="screen",
                parameters=[
                    {"robot_description": robot_description, "use_sim_time": False}
                ],
            ),
            # 3. ros2_control against the STM32 over micro-ROS
            Node(
                package="controller_manager",
                executable="ros2_control_node",
                name="controller_manager",
                namespace=namespace,
                output="screen",
                parameters=[
                    PathJoinSubstitution(
                        [FindPackageShare("neml_control"), "config", "controllers.yaml"]
                    ),
                    {"robot_description": robot_description},
                ],
            ),
            *controller_spawners,
            # 4. perception: raw frames stay on this machine (SS17.2)
            Node(
                package="neml_perception",
                executable="camera_gate",
                name="camera_gate",
                namespace=namespace,
                output="screen",
                parameters=[params_file],
            ),
            # 5. swarm link guard (T-083)
            Node(
                package="neml_swarm",
                executable="link_guard",
                name="link_guard",
                namespace=namespace,
                output="screen",
                respawn=True,
                respawn_delay=0.5,
                parameters=[params_file],
            ),
            # Enabled after device key, report spool and independent verifier are provisioned.
            Node(
                package="neml_swarm",
                executable="feedback_monitor",
                name="feedback_monitor",
                namespace=namespace,
                output="screen",
                condition=IfCondition(LaunchConfiguration("enable_learning_feedback")),
            ),
        ]
    )
