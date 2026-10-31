# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Watchdog monitor: LEVEL 1 (software) of the NEML_SPEC.md SS5.1 safety
chain, and the node that makes T-074 measurable (an e-stop event reaches the
whole stack in under 50 ms).

THIS IS L1. IT CANNOT SUBSTITUTE FOR THE L0 HARDWARE RELAY.
    SS5.1 is titled "L0 - Donanim guvenligi (yazilimdan bagimsiz)": hardware
    safety, independent of software. That independence is the property that
    makes it safety. This file is software, so it is not L0 and no amount of
    work on it ever will be.

    L0 is an ATmega328P, a normally-closed mushroom button and a contactor. The
    relay opens 150 ms after the heartbeat stops, and it opens the instant the
    NC loop breaks, whether this process is alive, wedged, killed, or was never
    started. A hardware shunt and comparator cut at 20 A with no software in
    the loop at all.

    L1 - this node - reports what L0 already did and stops the rest of the
    stack from commanding motion into dead motors. It removes no power. A build
    that is missing the relay, the watchdog MCU or the current comparator is
    unsafe, and "neml_safety is running" is not an argument against that. Do
    not let a review conclude otherwise on the strength of this file.

WHAT THIS NODE IS
    The thing that tells the rest of ROS 2 what the hardware already did, fast
    enough that no controller keeps streaming setpoints into dead motors, and
    the thing that refuses to resume without a human.

INDEPENDENCE FROM THE BRAIN
    Nothing here imports neml-brain, calls the LLM, or reaches the network. It
    runs in its own process from safety.launch.py. If neml-brain crashes, this
    node keeps publishing and keeps the latch closed.

T-074 BUDGET (worst case, e-stop pressed to motors_enabled=false on the wire)
    e-stop sampling on the aux MCU   10 ms  (100 Hz publisher)
    transport to this node            ~1 ms
    evaluation timer phase            5 ms  (200 Hz)
    publish + transport               ~1 ms
    --------------------------------------
    ~17 ms, with 33 ms of headroom against the 50 ms criterion.

    Those are estimates, so the node measures the part it can see: every
    latching event opens a propagation.Trace on a monotonic clock at ingress
    and stamps it again once the stop is on the wire. Blowing the budget is
    logged as an error with the per-hop breakdown, and the last trace stays on
    the node for a launch test to read. The remaining hops - the aux MCU and
    each subscriber - stamp themselves; see README.md.

INDEPENDENCE FROM THE BRAIN, AGAIN
    Nothing in this file imports neml-brain, and nothing in it is allowed to.
    If the brain crashes, is restarted, or is deliberately stopped, this node
    keeps evaluating, keeps publishing, and keeps the latch closed. The status
    topic is TRANSIENT_LOCAL, so anything that comes up afterwards is told the
    robot is latched before it has a chance to command anything.
"""

import rclpy
from neml_msgs.msg import SafetyStatus
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)
from std_msgs.msg import Bool, Header, UInt8
from std_srvs.srv import Trigger

from neml_safety.latch import (
    REASON_ESTOP,
    REASON_LINK_LOSS,
    REASON_NONE,
    REASON_OPERATOR,
    REASON_OVERCURRENT,
    REASON_OVERTEMP,
    REASON_WATCHDOG_TIMEOUT,
    SafetyLatch,
)
from neml_safety.propagation import ESTOP_BUDGET_MS, Trace, now_ns

# The pure module mirrors the message constants. Fail loudly at import if they
# ever drift instead of silently reporting the wrong cause to the operator.
# Raised, not asserted: `python -O` strips asserts, and a safety check that
# disappears under an optimisation flag is not a safety check.
if (REASON_NONE, REASON_ESTOP, REASON_WATCHDOG_TIMEOUT, REASON_OVERCURRENT,
        REASON_OVERTEMP, REASON_LINK_LOSS, REASON_OPERATOR) != (
    SafetyStatus.REASON_NONE,
    SafetyStatus.REASON_ESTOP,
    SafetyStatus.REASON_WATCHDOG_TIMEOUT,
    SafetyStatus.REASON_OVERCURRENT,
    SafetyStatus.REASON_OVERTEMP,
    SafetyStatus.REASON_LINK_LOSS,
    SafetyStatus.REASON_OPERATOR,
):
    raise RuntimeError(
        "neml_safety.latch REASON_* no longer match neml_msgs/SafetyStatus; "
        "the operator would be told the wrong cause for a stop"
    )

# SS17.2 QoS table, only the three classes this node touches.
TELEMETRY_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)
CMD_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
STATE_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)


class WatchdogMonitor(Node):
    def __init__(self) -> None:
        super().__init__("watchdog_monitor")

        # Every topic name is a parameter; bringup supplies them from YAML.
        self.declare_parameter("heartbeat_topic", "telemetry/watchdog_heartbeat")
        self.declare_parameter("estop_topic", "telemetry/estop")
        self.declare_parameter("status_topic", "state/safety")
        self.declare_parameter("motor_enable_topic", "cmd/motor_enable")
        self.declare_parameter("trip_topic", "cmd/safety_trip")
        self.declare_parameter("reset_service", "safety/reset")
        self.declare_parameter("heartbeat_timeout_s", 0.150)
        self.declare_parameter("evaluate_rate_hz", 200.0)
        self.declare_parameter("keepalive_period_s", 0.200)
        self.declare_parameter("start_latched", True)
        self.declare_parameter("propagation_budget_ms", ESTOP_BUDGET_MS)

        timeout_s = self.get_parameter("heartbeat_timeout_s").value
        self._keepalive_s = self.get_parameter("keepalive_period_s").value
        self._latch = SafetyLatch(
            heartbeat_timeout_s=timeout_s,
            start_latched=self.get_parameter("start_latched").value,
        )
        self._last_published: SafetyStatus | None = None
        self._last_publish_t = 0.0
        self._budget_ms = self.get_parameter("propagation_budget_ms").value
        # T-074 evidence. The launch test reads this; so can anyone with a
        # debugger after an incident.
        self.last_trace: Trace | None = None

        self._status_pub = self.create_publisher(
            SafetyStatus, self.get_parameter("status_topic").value, STATE_QOS
        )
        # The stack-wide kill line. Controllers and the swarm coordinator
        # subscribe to this, not to the status message, so reacting costs one
        # boolean compare.
        self._enable_pub = self.create_publisher(
            Bool, self.get_parameter("motor_enable_topic").value, CMD_QOS
        )

        # BEST_EFFORT on the e-stop line is the SS17.2 telemetry class and is
        # safe here because latching is level-triggered, not edge-triggered:
        # the aux MCU republishes at 100 Hz, so a lost datagram costs 10 ms,
        # and the relay never depended on this path in the first place.
        self.create_subscription(
            Header,
            self.get_parameter("heartbeat_topic").value,
            self._on_heartbeat,
            TELEMETRY_QOS,
        )
        self.create_subscription(
            Bool, self.get_parameter("estop_topic").value, self._on_estop, TELEMETRY_QOS
        )

        # External trips: link loss (T-083), overcurrent, overtemp, operator.
        # RELIABLE, because a trip request that is dropped is a robot that
        # keeps walking.
        self.create_subscription(
            UInt8, self.get_parameter("trip_topic").value, self._on_trip, CMD_QOS
        )

        self.create_service(
            Trigger, self.get_parameter("reset_service").value, self._on_reset
        )

        rate_hz = self.get_parameter("evaluate_rate_hz").value
        self.create_timer(1.0 / rate_hz, self._evaluate)

        self.get_logger().info(
            f"watchdog_monitor up: timeout {timeout_s * 1000:.0f} ms, "
            f"evaluating at {rate_hz:.0f} Hz. The L0 relay is hardware and is "
            f"not replaced by this node."
        )

    # ------------------------------------------------------------------ time
    def _now(self) -> float:
        """Seconds from the node clock, so a sim run obeys SS11.2 rule 4 (sim
        time only, never wall clock)."""
        return self.get_clock().now().nanoseconds * 1e-9

    # ---------------------------------------------------------------- inputs
    def _on_heartbeat(self, _msg: Header) -> None:
        self._latch.heartbeat(self._now())

    def _on_estop(self, msg: Bool) -> None:
        # Ingress first, before any work: this is the zero of the T-074 budget.
        trace = Trace(now_ns(), label="estop")
        now = self._now()
        self._latch.set_estop(msg.data, now)
        if msg.data:
            # Do not wait for the next timer tick: publish on the callback.
            self._publish(now, force=True)
            self._close_trace(trace)

    def _on_trip(self, msg: UInt8) -> None:
        trace = Trace(now_ns(), label=f"trip:{msg.data}")
        now = self._now()
        self._latch.trip(int(msg.data), now)
        self.get_logger().error(f"external trip, reason {msg.data}")
        self._publish(now, force=True)
        self._close_trace(trace)

    def _close_trace(self, trace: Trace) -> None:
        """Stamp the stop as it leaves this node and judge it against T-074.

        Only the in-process hops are ours to measure. An over-budget line here
        means this node is the problem; the budget still being blown while this
        line says ok means the aux MCU or a subscriber is, and the README says
        how to stamp those.
        """
        trace.record("published")
        self.last_trace = trace
        if trace.over_budget(self._budget_ms):
            self.get_logger().error(f"T-074 {trace.report(self._budget_ms)}")
        else:
            self.get_logger().info(f"T-074 {trace.report(self._budget_ms)}")

    def _on_reset(self, _request, response):
        ok, message = self._latch.reset(self._now())
        response.success = ok
        response.message = message
        self.get_logger().warning(f"operator reset requested: {message}")
        self._publish(self._now(), force=True)
        return response

    # --------------------------------------------------------------- outputs
    def _evaluate(self) -> None:
        self._publish(self._now())

    def _publish(self, now: float, force: bool = False) -> None:
        verdict = self._latch.evaluate(now)

        msg = SafetyStatus()
        msg.header = Header()
        # The evaluation instant on the NODE clock, which is the sim clock when
        # use_sim_time is on. Good for ordering and for logs; NOT the T-074
        # budget. A subscriber that wants its leg of the 50 ms stamps
        # propagation.now_ns() in its own callback and compares it with a
        # monotonic ingress stamp - see propagation.py and README.md.
        msg.header.stamp.sec = int(now)
        msg.header.stamp.nanosec = int((now - int(now)) * 1e9)
        msg.header.frame_id = "base_link"
        msg.estop_engaged = verdict.estop_engaged
        msg.watchdog_ok = verdict.watchdog_ok
        # SafetyStatus.heartbeat_age_s is a float64; +inf is a legal double and
        # says "never seen" more honestly than a magic number.
        msg.heartbeat_age_s = verdict.heartbeat_age_s
        msg.latched = verdict.latched
        msg.reason = verdict.reason
        msg.motors_enabled = verdict.motors_enabled
        msg.reset_required = verdict.reset_required
        latched_at = self._latch.latched_at
        if latched_at is not None:
            msg.latched_at.sec = int(latched_at)
            msg.latched_at.nanosec = int((latched_at - int(latched_at)) * 1e9)

        changed = self._last_published is None or (
            (
                self._last_published.latched,
                self._last_published.reason,
                self._last_published.estop_engaged,
                self._last_published.watchdog_ok,
            )
            != (msg.latched, msg.reason, msg.estop_engaged, msg.watchdog_ok)
        )
        if not (force or changed or now - self._last_publish_t >= self._keepalive_s):
            return

        self._status_pub.publish(msg)
        self._enable_pub.publish(Bool(data=verdict.motors_enabled))
        self._last_published = msg
        self._last_publish_t = now


def main(args=None) -> None:
    rclpy.init(args=args)
    node = WatchdogMonitor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
