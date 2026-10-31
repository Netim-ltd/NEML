# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Link guard - the robot-side half of T-083: the robot reaches a safe state
within 2 seconds of losing the coordinator.

THE DECISION IS LOCAL. The guard times out on peer liveness from its own
clock and trips by itself. It never waits to be told to stop, because the thing
that would do the telling - the coordinator, the lab station, the brain - is on
the far side of exactly the link that was lost. A robot that needed permission
to stop would keep walking.

It does not implement its own stop either. It trips the neml_safety latch with
REASON_LINK_LOSS, so a link loss ends up in exactly the same latched state,
with the same operator reset requirement, as an e-stop. One stop path, one
place to audit.

Trip margin: it fires at trip_fraction of the deadline (0.8 -> 1.6 s), so the
transition has completed by 2.0 s rather than only starting there. The
arithmetic lives in assignment.trip_deadline_s so it can be tested without a
ROS graph and without waiting two real seconds.

IT CLOSES THE LOOP. Publishing a trip is not reaching a safe state. The trip
topic is RELIABLE but VOLATILE, so a trip sent while watchdog_monitor is
restarting is a trip nobody hears, and the robot would keep moving with the log
claiming it had stopped. The guard therefore watches state/safety and keeps
asking until the latch reports itself closed. Missing that confirmation inside
assignment.confirm_budget_s is a T-083 breach and is logged as one - loudly,
because this node cannot cut power. Only the SS5.1 L0 relay can.

Re-arming: when the operator clears the latch the guard arms again and gives
the link one fresh deadline to come back before it trips a second time. That is
deliberate. With the coordinator down, a robot cannot be reset into free
running - T-083 has no exception for an impatient human. Bench work without a
coordinator sets link_timeout_s, or does not run this node.
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
from std_msgs.msg import String, UInt8

from neml_swarm.assignment import (
    LINK_TIMEOUT_S,
    TRIP_FRACTION,
    confirm_budget_s,
    is_stale,
    trip_deadline_s,
)

CMD_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
# SS17.2 /*/state: the latched status is TRANSIENT_LOCAL, so a guard that comes
# up after the watchdog is told the robot is latched instead of waiting for the
# next keepalive.
STATE_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)


class LinkGuard(Node):
    def __init__(self) -> None:
        super().__init__("link_guard")

        self.declare_parameter("heartbeat_topic", "/swarm/coordinator_heartbeat")
        self.declare_parameter("trip_topic", "cmd/safety_trip")
        self.declare_parameter("safety_status_topic", "state/safety")
        self.declare_parameter("link_timeout_s", LINK_TIMEOUT_S)
        self.declare_parameter("trip_fraction", TRIP_FRACTION)
        self.declare_parameter("check_rate_hz", 20.0)

        timeout_s = self.get_parameter("link_timeout_s").value
        fraction = self.get_parameter("trip_fraction").value
        self._deadline_s = trip_deadline_s(timeout_s, fraction)
        self._confirm_budget_s = confirm_budget_s(timeout_s, fraction)
        # Start the clock at boot, not at None: the guard gives the coordinator
        # one full deadline to show up instead of tripping on the first tick.
        self._last_seen: float | None = self._now()
        self._tripped_at: float | None = None
        self._latched = False
        self._breach_logged = False

        self.create_subscription(
            String, self.get_parameter("heartbeat_topic").value, self._on_beat, CMD_QOS
        )
        self.create_subscription(
            SafetyStatus,
            self.get_parameter("safety_status_topic").value,
            self._on_safety,
            STATE_QOS,
        )
        self._trip_pub = self.create_publisher(
            UInt8, self.get_parameter("trip_topic").value, CMD_QOS
        )
        self.create_timer(
            1.0 / self.get_parameter("check_rate_hz").value, self._check
        )
        self.get_logger().info(
            f"link_guard up: safe state requested after {self._deadline_s:.2f} s "
            f"of coordinator silence (T-083 deadline {LINK_TIMEOUT_S:.1f} s)."
        )

    def _now(self) -> float:
        return self.get_clock().now().nanoseconds * 1e-9

    def _on_beat(self, _msg: String) -> None:
        self._last_seen = self._now()
        # Deliberately does NOT cancel a trip in flight: the latch needs an
        # operator reset, and clearing here would let a flapping link silently
        # bring the robot back up.

    def _on_safety(self, msg: SafetyStatus) -> None:
        """The confirmation half of the loop, and the only place the guard
        re-arms."""
        was_latched = self._latched
        self._latched = msg.latched
        if was_latched and not msg.latched:
            # Operator cleared it. Arm again with a fresh deadline so the link
            # gets the same grace it gets at boot, and no longer.
            self._last_seen = self._now()
            self._tripped_at = None
            self._breach_logged = False
            self.get_logger().warning("latch cleared - link guard armed again")

    def _check(self) -> None:
        now = self._now()

        if self._tripped_at is None:
            if not is_stale(self._last_seen, now, self._deadline_s):
                return
            self._tripped_at = now
            self._breach_logged = False
            self.get_logger().error("coordinator link lost - requesting safe state")
        elif self._latched:
            return  # the robot is safe; nothing left to ask for

        # Not latched yet: keep asking. One publish is not a safe state - the
        # trip topic is VOLATILE, so a watchdog that was restarting never heard
        # the first one.
        self._trip_pub.publish(UInt8(data=SafetyStatus.REASON_LINK_LOSS))

        if not self._breach_logged and now - self._tripped_at > self._confirm_budget_s:
            self._breach_logged = True
            self.get_logger().error(
                f"T-083 BREACH: no latched SafetyStatus {now - self._tripped_at:.2f} s "
                f"after the trip (budget {self._confirm_budget_s:.2f} s). The robot is "
                f"NOT known to be safe. Only the SS5.1 L0 relay can stop it now."
            )


def main(args=None) -> None:
    rclpy.init(args=args)
    node = LinkGuard()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
