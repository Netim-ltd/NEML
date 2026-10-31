# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""launch_testing stub for T-083 on a live graph (SS18.1: launch tests on all
bringup).

The acceptance criterion is a stopwatch: "Robot 2 s icinde guvenli duruma
geciyor". So this brings up link_guard with NO coordinator anywhere - which is
exactly the failure it exists for - and measures how long it takes to ask for
the safe state. The arithmetic is covered without ROS in test_assignment.py;
what only a live graph can fail is the timer actually firing, the topic name,
and the QoS matching on the other end.

It also checks the part a pure test cannot reach: the guard keeps asking until
the latch answers. A single VOLATILE publish into a watchdog that happened to
be restarting is a robot that never stopped while the log says it did.

The probe deliberately never confirms. A real robot's latched SafetyStatus
would stop the repeats; here nothing does, so the repeat path is what runs.

Not runnable on the Windows development host: it needs a sourced ROS 2 install.
It skips there and runs on the Ubuntu robot host under colcon test.
"""

import time
import unittest

import pytest

pytest.importorskip("launch_testing", reason="launch_testing comes from a sourced ROS 2 install")
pytest.importorskip("rclpy")

import launch_testing.actions  # noqa: E402
import launch_testing.asserts  # noqa: E402
import launch_testing.markers  # noqa: E402
import rclpy  # noqa: E402
from launch import LaunchDescription  # noqa: E402
from launch_ros.actions import Node as LaunchNode  # noqa: E402
from neml_msgs.msg import SafetyStatus  # noqa: E402
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy  # noqa: E402
from std_msgs.msg import UInt8  # noqa: E402

from neml_swarm.assignment import LINK_TIMEOUT_S  # noqa: E402

NAMESPACE = "t083_robot"
# SS17.2 /*/cmd/*
CMD_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)


@pytest.mark.launch_test
@launch_testing.markers.keep_alive
def generate_test_description():
    guard = LaunchNode(
        package="neml_swarm",
        executable="link_guard",
        name="link_guard",
        namespace=NAMESPACE,
        output="screen",
        # Defaults on purpose: the criterion is 2 s, so the test has to run
        # against 2 s. No coordinator is started - that is the whole scenario.
    )
    return LaunchDescription([guard, launch_testing.actions.ReadyToTest()])


class TestLinkGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rclpy.init()
        cls.node = rclpy.create_node("link_guard_probe")
        cls.trips: list[UInt8] = []
        cls.node.create_subscription(
            UInt8, f"/{NAMESPACE}/cmd/safety_trip", cls.trips.append, CMD_QOS
        )

    @classmethod
    def tearDownClass(cls):
        cls.node.destroy_node()
        rclpy.shutdown()

    def _spin_until(self, predicate, timeout_s):
        end = time.monotonic() + timeout_s
        while not predicate() and time.monotonic() < end:
            rclpy.spin_once(self.node, timeout_sec=0.02)
        return predicate()

    def test_losing_the_coordinator_asks_for_the_safe_state_inside_two_seconds(self):
        """T-083. Nobody tells the robot to stop: the guard decides locally,
        from its own clock, because the coordinator is what it lost."""
        started = time.monotonic()
        self.assertTrue(
            self._spin_until(lambda: bool(self.trips), 10.0),
            "the guard never asked for a safe state",
        )
        elapsed = time.monotonic() - started
        self.assertLess(
            elapsed,
            LINK_TIMEOUT_S,
            f"safe state requested {elapsed:.2f} s after the probe started; "
            f"T-083 allows {LINK_TIMEOUT_S:.1f} s",
        )
        self.assertEqual(self.trips[0].data, SafetyStatus.REASON_LINK_LOSS)

    def test_it_keeps_asking_until_something_latches(self):
        """The trip topic is VOLATILE. One publish into a watchdog that was
        restarting is a robot that never stopped."""
        self.trips.clear()
        self.assertTrue(
            self._spin_until(lambda: len(self.trips) >= 2, 5.0),
            "the guard trips once and gives up",
        )
        self.assertTrue(all(msg.data == SafetyStatus.REASON_LINK_LOSS for msg in self.trips))


@launch_testing.post_shutdown_test()
class TestLinkGuardShutdown(unittest.TestCase):
    def test_exits_cleanly(self, proc_info):
        launch_testing.asserts.assertExitCodes(proc_info, allowable_exit_codes=[0, -2, -15])
