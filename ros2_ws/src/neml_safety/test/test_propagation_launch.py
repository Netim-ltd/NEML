# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""launch_testing stub that measures T-074 on a live graph (SS18.1: launch
tests on all bringup).

This is the test that makes the 50 ms a number instead of a claim. It brings up
the real safety stack, stamps a monotonic clock immediately before putting the
e-stop on the wire, stamps it again in the subscriber callback, and asserts the
difference against propagation.ESTOP_BUDGET_MS.

What it covers, honestly: the transport plus this node, on one host, with the
CI machine's scheduling. That is the software leg of the budget. The aux MCU
sampling period and the motor relay are hardware and belong to T-075 with an
oscilloscope - no ROS test can measure them, and a green run here is not a
substitute for that measurement or for the L0 relay existing at all.

Not runnable on the Windows development host: it needs a sourced ROS 2 install.
It skips there and runs on the Ubuntu robot host under colcon test.
"""

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
from launch_ros.substitutions import FindPackageShare  # noqa: E402
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy  # noqa: E402
from std_msgs.msg import Bool  # noqa: E402

from neml_msgs.msg import SafetyStatus  # noqa: E402

from neml_safety.propagation import ESTOP_BUDGET_MS, Trace, now_ns  # noqa: E402

NAMESPACE = "budget_robot"
# SS17.2 /*/state
STATE_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)
# SS17.2 /*/telemetry/*
TELEMETRY_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.VOLATILE,
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


class TestPropagationBudget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rclpy.init()
        cls.node = rclpy.create_node("propagation_probe")

    @classmethod
    def tearDownClass(cls):
        cls.node.destroy_node()
        rclpy.shutdown()

    def _spin_until(self, predicate, timeout_s):
        end = self.node.get_clock().now().nanoseconds + int(timeout_s * 1e9)
        while not predicate() and self.node.get_clock().now().nanoseconds < end:
            rclpy.spin_once(self.node, timeout_sec=0.05)
        return predicate()

    def test_estop_reaches_a_subscriber_inside_the_t074_budget(self):
        received: list[tuple[SafetyStatus, int]] = []
        self.node.create_subscription(
            SafetyStatus,
            f"/{NAMESPACE}/state/safety",
            # Stamp on arrival, before anything else in the callback.
            lambda msg: received.append((msg, now_ns())),
            STATE_QOS,
        )
        estop = self.node.create_publisher(
            Bool, f"/{NAMESPACE}/telemetry/estop", TELEMETRY_QOS
        )

        self.assertTrue(
            self._spin_until(lambda: bool(received), 10.0), "no SafetyStatus within 10 s"
        )
        self.assertTrue(
            self._spin_until(lambda: estop.get_subscription_count() > 0, 10.0),
            "watchdog_monitor never subscribed to the e-stop line",
        )
        received.clear()

        # Ingress: the last instant before the event exists anywhere.
        trace = Trace(now_ns(), label="estop end-to-end")
        estop.publish(Bool(data=True))

        engaged = self._spin_until(
            lambda: any(msg.estop_engaged for msg, _ in received), ESTOP_BUDGET_MS / 100.0
        )
        self.assertTrue(engaged, "the e-stop never came back out of the safety stack")

        arrival = next(at for msg, at in received if msg.estop_engaged)
        trace.record("subscriber", arrival)
        self.assertFalse(trace.over_budget(), trace.report())

    def test_the_stack_stays_latched_with_no_brain_running(self):
        """Nothing in this launch file is neml-brain, and the latch holds
        anyway. TRANSIENT_LOCAL means a late subscriber is told immediately."""
        late: list[SafetyStatus] = []
        self.node.create_subscription(
            SafetyStatus, f"/{NAMESPACE}/state/safety", late.append, STATE_QOS
        )
        self.assertTrue(self._spin_until(lambda: bool(late), 5.0), "no latched status")
        self.assertTrue(late[-1].latched)
        self.assertFalse(late[-1].motors_enabled)


@launch_testing.post_shutdown_test()
class TestPropagationShutdown(unittest.TestCase):
    def test_exits_cleanly(self, proc_info):
        launch_testing.asserts.assertExitCodes(proc_info, allowable_exit_codes=[0, -2, -15])
