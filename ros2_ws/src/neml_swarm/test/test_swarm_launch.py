# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""launch_testing stub for the swarm stack (SS18.1: launch tests on all
bringup).

It brings up the real coordinator from neml_bringup and two lease agents, then
drops an already-expired lease for a robot that is not there onto the swarm
network and watches a survivor take the task. That is T-082 on a live graph.

The agents are started here as plain Node actions rather than from a launch
file because this is a two-robot fixture on one host; the per-robot agent
belongs in neml_bringup/launch/robot.launch.py, which is not this package's to
edit (see the milestone notes).

The lease arithmetic itself is covered without a ROS graph in test_lease.py.
What this adds is the part only a live graph can fail: QoS mismatches, topic
names, and two agents deciding at the same time.

Not runnable on the Windows development host: it needs a sourced ROS 2 install.
It skips there and runs on the Ubuntu host under colcon test.
"""

import json
import unittest

import pytest

pytest.importorskip("launch_testing", reason="launch_testing comes from a sourced ROS 2 install")
pytest.importorskip("rclpy")

import launch_testing.actions  # noqa: E402
import launch_testing.asserts  # noqa: E402
import launch_testing.markers  # noqa: E402
import rclpy  # noqa: E402
from launch import LaunchDescription  # noqa: E402
from launch.actions import IncludeLaunchDescription  # noqa: E402
from launch.launch_description_sources import PythonLaunchDescriptionSource  # noqa: E402
from launch.substitutions import PathJoinSubstitution  # noqa: E402
from launch_ros.actions import Node as LaunchNode  # noqa: E402
from launch_ros.substitutions import FindPackageShare  # noqa: E402
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy  # noqa: E402
from std_msgs.msg import String  # noqa: E402

from neml_msgs.msg import RobotState  # noqa: E402

from neml_swarm.lease import Lease, decode, encode  # noqa: E402

FLEET = ["r01", "r02"]
RENEW_TOPIC = "/swarm/telemetry/lease"
CLAIM_TOPIC = "/swarm/cmd/lease_claim"

# SS17.2 QoS table, the same three profiles the nodes declare.
STATE_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)
CMD_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
TELEMETRY_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)


@pytest.mark.launch_test
@launch_testing.markers.keep_alive
def generate_test_description():
    coordinator = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution(
                [FindPackageShare("neml_bringup"), "launch", "swarm.launch.py"]
            )
        )
    )
    agents = [
        LaunchNode(
            package="neml_swarm",
            executable="lease_agent",
            name="lease_agent",
            namespace=robot,
            output="screen",
            parameters=[{"robot_id": robot, "peers": FLEET}],
        )
        for robot in FLEET
    ]
    return LaunchDescription(
        [coordinator, *agents, launch_testing.actions.ReadyToTest()]
    )


class TestSwarmBringup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rclpy.init()
        cls.node = rclpy.create_node("swarm_launch_probe")
        cls.claims: list[Lease] = []
        cls.node.create_subscription(
            String, CLAIM_TOPIC, cls._on_claim, CMD_QOS
        )
        cls.renew_pub = cls.node.create_publisher(String, RENEW_TOPIC, TELEMETRY_QOS)
        cls.state_pubs = {
            robot: cls.node.create_publisher(
                RobotState, f"/{robot}/state/robot", STATE_QOS
            )
            for robot in FLEET
        }

    @classmethod
    def _on_claim(cls, msg: String) -> None:
        lease = decode(msg.data)
        if lease is not None:
            cls.claims.append(lease)

    @classmethod
    def tearDownClass(cls):
        cls.node.destroy_node()
        rclpy.shutdown()

    def _now_s(self) -> float:
        return self.node.get_clock().now().nanoseconds * 1e-9

    def _spin_until(self, predicate, timeout_s):
        end = self.node.get_clock().now().nanoseconds + int(timeout_s * 1e9)
        while not predicate() and self.node.get_clock().now().nanoseconds < end:
            rclpy.spin_once(self.node, timeout_sec=0.05)
        return predicate()

    def _announce_idle(self, robot: str) -> None:
        """An idle, unlatched robot. Until an agent hears this it refuses to
        claim anything, which is the safe default."""
        msg = RobotState()
        msg.robot_id = robot
        msg.mode = RobotState.MODE_IDLE
        msg.active_task_id = ""
        self.state_pubs[robot].publish(msg)

    def test_coordinator_heartbeat_is_on_the_wire(self):
        """The robot-side link guard trips into the T-083 safe state when this
        stops. If it never starts, every robot latches 1.6 s after boot."""
        beats: list[String] = []
        self.node.create_subscription(
            String, "/swarm/coordinator_heartbeat", beats.append, CMD_QOS
        )
        self.assertTrue(
            self._spin_until(lambda: len(beats) >= 2, 10.0), "no coordinator heartbeat"
        )

    def test_an_expired_lease_is_taken_over_by_exactly_one_survivor(self):
        """T-082. r99 held t1 and stopped renewing; the fleet takes the work
        without anybody being told to, and without two robots taking it."""
        for robot in FLEET:
            self._announce_idle(robot)
        self.assertTrue(
            self._spin_until(lambda: self.renew_pub.get_subscription_count() >= 2, 10.0),
            "the lease agents never subscribed",
        )
        self.claims.clear()

        orphan = Lease("t1", "r99", 0, self._now_s() - 1.0)
        self.renew_pub.publish(String(data=encode(orphan)))

        self.assertTrue(
            self._spin_until(lambda: bool(self.claims), 5.0), "nobody took the orphan"
        )
        holders = {lease.holder for lease in self.claims if lease.task_id == "t1"}
        self.assertEqual(len(holders), 1, f"{holders} all claimed the same task")
        self.assertIn(holders.pop(), FLEET)
        self.assertTrue(all(lease.epoch > orphan.epoch for lease in self.claims))

    def test_the_assignment_plan_is_json(self):
        """Advisory only - the lease is what binds - but the schema is what
        neml-brain reads, so it has to stay parseable."""
        plans: list[String] = []
        self.node.create_subscription(
            String, "/swarm/assignments", plans.append, CMD_QOS
        )
        tasks = self.node.create_publisher(String, "/swarm/tasks", CMD_QOS)
        self.assertTrue(
            self._spin_until(lambda: tasks.get_subscription_count() > 0, 10.0),
            "the coordinator never subscribed to the task queue",
        )
        tasks.publish(
            String(data=json.dumps([{"task_id": "t9", "assigned_to": "r99", "priority": 0}]))
        )
        self.assertTrue(self._spin_until(lambda: bool(plans), 10.0), "no plan published")
        self.assertIsInstance(json.loads(plans[-1].data), dict)


@launch_testing.post_shutdown_test()
class TestSwarmShutdown(unittest.TestCase):
    def test_exits_cleanly(self, proc_info):
        launch_testing.asserts.assertExitCodes(proc_info, allowable_exit_codes=[0, -2, -15])
