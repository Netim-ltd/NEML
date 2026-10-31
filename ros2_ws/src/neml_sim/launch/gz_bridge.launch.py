# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""ros_gz_bridge wiring described by config/gz_bridge.yaml (NEML_SPEC.md SS11.1).

That config is fleet-wide and carries <ns>/<world> placeholders plus a
`qos_profiles` block. This launch file renders it for one robot in one world
and writes the result to a temporary file that ros_gz_bridge can load.

Known ceiling: Jazzy's ros_gz_bridge has no per-entry QoS setting, so the SS17.2
classes in that config stay declarative on the bridged topics and the bridge
uses its own defaults. Every publisher and subscriber NEML itself declares does
apply the table. ponytail: drop the renderer and pass the config straight
through the day upstream adds QoS support.

Config path: SS17.2 uses /srv/neml/config at deploy time, which is where this
argument points by default.
"""

import tempfile
from pathlib import Path

import yaml
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction, SetEnvironmentVariable
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from neml_sim.bridge_config import render_bridge_config


def _bridge_node(context, *_args, **_kwargs):
    namespace = LaunchConfiguration("namespace").perform(context)
    world = LaunchConfiguration("world").perform(context)
    config = Path(LaunchConfiguration("bridge_config").perform(context))

    entries = render_bridge_config(config.read_text(encoding="utf-8"), namespace, world)

    # ros_gz_bridge takes a file, not a string. Keep it beside the run so a
    # failed run can be inspected afterwards.
    rendered = Path(tempfile.gettempdir()) / f"neml_gz_bridge_{namespace}_{world}.yaml"
    rendered.write_text(yaml.safe_dump(entries, sort_keys=False), encoding="utf-8")

    return [
        Node(
            package="ros_gz_bridge",
            executable="parameter_bridge",
            name="gz_bridge",
            output="screen",
            parameters=[{"config_file": str(rendered), "use_sim_time": True}],
        )
    ]


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription(
        [
            DeclareLaunchArgument("namespace", default_value="r01"),
            DeclareLaunchArgument("world", default_value="flat"),
            DeclareLaunchArgument(
                "bridge_config",
                default_value="/srv/neml/config/gz_bridge.yaml",
                description="SS11.1 bridge map; SS17.2 deploy path.",
            ),
            SetEnvironmentVariable("ROS_DOMAIN_ID", "42"),
            SetEnvironmentVariable("RMW_IMPLEMENTATION", "rmw_zenoh_cpp"),
            OpaqueFunction(function=_bridge_node),
        ]
    )
