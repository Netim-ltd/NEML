# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Bridge config rendering. The fixture below mirrors the shape of
config/gz_bridge.yaml deliberately: the test stays hermetic, so it does not
break when the deployed config gains a topic."""

import pytest
import yaml

from neml_sim.bridge_config import qos_class_of, render_bridge_config

RAW = """
qos_profiles:
  telemetry: {reliability: best_effort, durability: volatile, history: keep_last, depth: 1}
  cmd:       {reliability: reliable,    durability: volatile, history: keep_last, depth: 10}

bridges:
  - ros_topic_name: "/clock"
    gz_topic_name: "/clock"
    ros_type_name: "rosgraph_msgs/msg/Clock"
    gz_type_name: "gz.msgs.Clock"
    direction: GZ_TO_ROS
    qos: state
  - ros_topic_name: "/<ns>/telemetry/imu"
    gz_topic_name: "/world/<world>/model/<ns>/link/base_link/sensor/imu/imu"
    ros_type_name: "sensor_msgs/msg/Imu"
    gz_type_name: "gz.msgs.IMU"
    direction: GZ_TO_ROS
    qos: telemetry
  - ros_topic_name: "/<ns>/cmd/vel"
    gz_topic_name: "/model/<ns>/cmd_vel"
    ros_type_name: "geometry_msgs/msg/Twist"
    gz_type_name: "gz.msgs.Twist"
    direction: ROS_TO_GZ
    qos: cmd
"""


def test_placeholders_are_substituted():
    entries = render_bridge_config(RAW, "r02", "maze")
    imu = entries[1]
    assert imu["ros_topic_name"] == "/r02/telemetry/imu"
    assert imu["gz_topic_name"] == "/world/maze/model/r02/link/base_link/sensor/imu/imu"


def test_topics_without_placeholders_survive_untouched():
    assert render_bridge_config(RAW, "r01", "flat")[0]["ros_topic_name"] == "/clock"


def test_neml_only_keys_are_stripped():
    """`qos` is NEML annotation; ros_gz_bridge would reject it."""
    for entry in render_bridge_config(RAW, "r01", "flat"):
        assert "qos" not in entry
        assert set(entry) == {
            "ros_topic_name",
            "gz_topic_name",
            "ros_type_name",
            "gz_type_name",
            "direction",
        }


def test_qos_profiles_block_never_reaches_the_bridge():
    rendered = yaml.safe_dump(render_bridge_config(RAW, "r01", "flat"))
    assert "qos_profiles" not in rendered


def test_direction_is_preserved():
    directions = [e["direction"] for e in render_bridge_config(RAW, "r01", "flat")]
    assert directions == ["GZ_TO_ROS", "GZ_TO_ROS", "ROS_TO_GZ"]


def test_declared_qos_class_is_readable():
    """The SS17.2 class stays queryable even though the bridge ignores it."""
    assert qos_class_of(RAW, "/<ns>/telemetry/imu") == "telemetry"
    assert qos_class_of(RAW, "/<ns>/cmd/vel") == "cmd"
    assert qos_class_of(RAW, "/nope") is None


def test_missing_namespace_is_an_error_not_a_dead_bridge():
    with pytest.raises(ValueError):
        render_bridge_config(RAW, "", "flat")


def test_unsubstituted_placeholder_is_an_error():
    broken = RAW.replace("<ns>/cmd/vel", "<robot>/cmd/vel")
    with pytest.raises(ValueError, match="placeholder"):
        render_bridge_config(broken, "r01", "flat")


def test_empty_config_is_an_error():
    with pytest.raises(ValueError):
        render_bridge_config("bridges: []", "r01", "flat")
