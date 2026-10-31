# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""T-034: the sim server and config/gz_bridge.yaml must name the same topics.

The server echoes Gazebo topics directly and the bridge republishes the same
topics to ROS 2. They are two files, so they drift. This reconciles them: a
topic that exists on one side only fails here rather than as a silent absence of
sensor data six weeks later.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from mcp_servers.neml_mcp_sim import server

BRIDGE_PATH = server.REPO_ROOT / "config" / "gz_bridge.yaml"
BRIDGE: dict[str, Any] = yaml.safe_load(BRIDGE_PATH.read_text(encoding="utf-8"))
ENTRIES: list[dict[str, Any]] = BRIDGE["bridges"]

# SENSOR_UNITS names are SI-table names; the bridge names its ROS topics after
# the message, not the quantity. This is the only place the two vocabularies meet.
SENSOR_TO_ROS_TOPIC = {
    "imu": "/<ns>/telemetry/imu",
    "encoder": "/<ns>/telemetry/joint_states",
    "contact": "/<ns>/telemetry/contacts",
    "lidar": "/<ns>/telemetry/scan",
}


def gz_topic_of(ros_topic: str) -> str:
    return str(next(e["gz_topic_name"] for e in ENTRIES if e["ros_topic_name"] == ros_topic))


@pytest.mark.parametrize("sensor", sorted(SENSOR_TO_ROS_TOPIC))
def test_server_topic_matches_the_bridge_entry(sensor: str) -> None:
    expected = (
        gz_topic_of(SENSOR_TO_ROS_TOPIC[sensor]).replace("<world>", "flat").replace("<ns>", "r01")
    )
    assert server._topic(sensor, "flat", "r01") == expected


def test_neither_side_has_a_telemetry_topic_the_other_lacks() -> None:
    """The one-sided-topic check. Adding a row to either file fails this."""
    bridged = {
        e["ros_topic_name"] for e in ENTRIES if e["ros_topic_name"].startswith("/<ns>/telemetry/")
    }
    assert bridged == set(SENSOR_TO_ROS_TOPIC.values())
    assert set(SENSOR_TO_ROS_TOPIC) == set(server._SENSOR_TOPICS)


def test_every_readable_sensor_has_an_si_unit() -> None:
    assert set(server._SENSOR_TOPICS) <= set(server.SENSOR_UNITS)


def test_a_sensor_with_no_bridge_entry_is_a_typed_error() -> None:
    """`current` is real-robot telemetry (SPEC 17.2), nothing simulates it."""
    with pytest.raises(server.SimStateError):
        server._topic("current", "flat", "r01")


def test_telemetry_flows_out_of_gazebo_and_commands_flow_in() -> None:
    for entry in ENTRIES:
        ros_topic = entry["ros_topic_name"]
        if "/telemetry/" in ros_topic or ros_topic == "/clock":
            assert entry["direction"] == "GZ_TO_ROS", ros_topic
        else:
            assert entry["direction"] == "ROS_TO_GZ", ros_topic


def test_every_robot_topic_is_namespaced() -> None:
    """Two robots in one world must not share a topic (SPEC 17.2 <ns> classes)."""
    for entry in ENTRIES:
        if entry["ros_topic_name"] == "/clock":
            continue
        assert "<ns>" in entry["gz_topic_name"], entry["ros_topic_name"]
        assert entry["ros_topic_name"].startswith("/<ns>/"), entry["ros_topic_name"]


def test_the_five_worlds_the_launch_file_offers_are_the_five_on_disk() -> None:
    worlds = {p.stem for p in (server.REPO_ROOT / "ros2_ws/src/neml_sim/worlds").glob("*.sdf")}
    assert worlds == {"flat", "obstacle_low", "ramp_10deg", "rough_terrain", "maze"}
    launch = (server.REPO_ROOT / "ros2_ws/src/neml_sim/launch/gz_sim.launch.py").read_text(
        encoding="utf-8"
    )
    for world in worlds:
        assert f'"{world}"' in launch


def test_neml_services_wrap_json_in_a_stringmsg(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    seen: list[list[str]] = []

    async def fake_cli(argv: list[str], timeout_s: float) -> str:
        seen.append(argv)
        return 'data: "{\\"policy_sha256\\": \\"ab\\"}"'

    monkeypatch.setattr(server, "run_cli", fake_cli)
    out = asyncio.run(
        server.GzRunner().call("policy", {"world": "w", "req": {"ns": "r", "path": "p"}}, 5)
    )
    assert out == {"policy_sha256": "ab"}
    req = seen[0][seen[0].index("--req") + 1]
    assert req.startswith('data: "{\\"ns\\"')
