# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""launch_testing stub for safety.launch.py (SS18.1: launch tests on all
bringup).

Scope, on purpose: it starts the real safety stack and checks that the node
comes up, publishes, and shuts down cleanly. It does not assert the 50 ms
propagation of T-074 - that number is a hardware measurement taken with the
relay and an oscilloscope (T-075), and the latch logic behind it is covered
exhaustively by neml_safety/test/test_latch.py.

What this catches is the failure this whole package exists to prevent: the
safety stack not starting at all.
"""

import unittest

import launch_testing.actions
import launch_testing.asserts
import launch_testing.markers
import pytest
import rclpy
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

from neml_msgs.msg import SafetyStatus

NAMESPACE = "test_robot"
STATE_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)


@pytest.mark.launch_test
@launch_testing.markers.keep_alive
def generate_test_description():
    safety = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution(
                [FindPackageShare("neml_bringup"), "launch", "safety.launch.py"]
            )
        ),
        launch_arguments={"namespace": NAMESPACE, "respawn": "false"}.items(),
    )
    return LaunchDescription([safety, launch_testing.actions.ReadyToTest()])


class TestSafetyBringup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rclpy.init()
        cls.node = rclpy.create_node("safety_launch_probe")

    @classmethod
    def tearDownClass(cls):
        cls.node.destroy_node()
        rclpy.shutdown()

    def test_status_is_published_and_starts_latched(self):
        """A physical robot boots needing a human (SS5.1)."""
        received = []
        self.node.create_subscription(
            SafetyStatus,
            f"/{NAMESPACE}/state/safety",
            received.append,
            STATE_QOS,
        )
        end = self.node.get_clock().now().nanoseconds + 10_000_000_000
        while not received and self.node.get_clock().now().nanoseconds < end:
            rclpy.spin_once(self.node, timeout_sec=0.1)

        self.assertTrue(received, "no SafetyStatus within 10 s")
        status = received[-1]
        self.assertTrue(status.latched)
        self.assertTrue(status.reset_required)
        self.assertFalse(status.motors_enabled)

    def test_reset_service_is_offered(self):
        """Without it there is no way back from a latch except a power cycle."""
        names = dict(self.node.get_service_names_and_types())
        self.assertIn(f"/{NAMESPACE}/safety/reset", names)


@launch_testing.post_shutdown_test()
class TestSafetyShutdown(unittest.TestCase):
    def test_exits_cleanly(self, proc_info):
        # SIGINT/SIGTERM during shutdown are clean exits for an rclpy node.
        launch_testing.asserts.assertExitCodes(
            proc_info, allowable_exit_codes=[0, -2, -15]
        )
