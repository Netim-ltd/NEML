# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Lease agent - the robot-side half of T-082. One per robot.

Two jobs, both of them local decisions:

  RENEW   while this robot is working a task it republishes the lease for it.
          Stopping is how it gives the task up, and it stops the instant the
          safety latch closes - so the T-083 safe-state transition is also the
          moment the work becomes available to the rest of the fleet, without
          waiting out the full lease TTL.

  CLAIM   when a peer's lease expires, this robot may take it. It decides that
          from the ledger and its own clock. The coordinator is not asked and
          is not needed: a robot that can still hear one peer can still take
          over that peer's work, which is the whole point of doing ownership by
          lease on a WiFi swarm (SS17.2).

Claims are staggered by a per-task rank (lease.reclaim_delay_s) so three robots
do not grab the same orphan in the same millisecond. A robot that hears a
better claim during its own wait folds it into the ledger and stands down.

ponytail: the executor that actually runs a claimed task lives in neml-brain,
not here. This node subscribes to RobotState to learn what the robot is really
doing and publishes claims for the executor to pick up. If the executor does
not take a claimed task within one TTL, the claim is dropped and the task goes
back on offer rather than being held by a robot that is not doing it.
"""

import rclpy
from neml_msgs.msg import RobotState
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)
from std_msgs.msg import String

from neml_swarm.lease import (
    CLAIM_STAGGER_S,
    LEASE_TTL_S,
    Lease,
    claim,
    claimable,
    decode,
    encode,
    merge,
)

# SS17.2 QoS table.
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


class LeaseAgent(Node):
    def __init__(self) -> None:
        super().__init__("lease_agent")

        self.declare_parameter("robot_id", "r01")
        self.declare_parameter("peers", ["r01"])
        self.declare_parameter("robot_state_topic", "state/robot")
        self.declare_parameter("lease_renew_topic", "/swarm/telemetry/lease")
        self.declare_parameter("lease_claim_topic", "/swarm/cmd/lease_claim")
        self.declare_parameter("lease_ttl_s", LEASE_TTL_S)
        self.declare_parameter("claim_stagger_s", CLAIM_STAGGER_S)
        # Four renewals per TTL: three may be lost on the BEST_EFFORT telemetry
        # class before a healthy robot looks dead.
        self.declare_parameter("renew_rate_hz", 2.0)
        self.declare_parameter("tick_rate_hz", 10.0)

        self._robot_id = self.get_parameter("robot_id").value
        self._peers = set(self.get_parameter("peers").value) | {self._robot_id}
        self._ttl_s = self.get_parameter("lease_ttl_s").value
        self._stagger_s = self.get_parameter("claim_stagger_s").value

        self._ledger: dict[str, Lease] = {}
        self._active = ""  # what the robot is really running, from RobotState
        self._claimed: str | None = None  # taken here, executor has not caught up
        self._claimed_at = 0.0
        self._blocked = True  # RobotState has not arrived yet: assume unsafe

        self.create_subscription(
            RobotState,
            self.get_parameter("robot_state_topic").value,
            self._on_state,
            STATE_QOS,
        )
        self.create_subscription(
            String,
            self.get_parameter("lease_renew_topic").value,
            self._on_lease,
            TELEMETRY_QOS,
        )
        self.create_subscription(
            String,
            self.get_parameter("lease_claim_topic").value,
            self._on_lease,
            CMD_QOS,
        )
        self._renew_pub = self.create_publisher(
            String, self.get_parameter("lease_renew_topic").value, TELEMETRY_QOS
        )
        self._claim_pub = self.create_publisher(
            String, self.get_parameter("lease_claim_topic").value, CMD_QOS
        )

        self.create_timer(1.0 / self.get_parameter("renew_rate_hz").value, self._renew)
        self.create_timer(1.0 / self.get_parameter("tick_rate_hz").value, self._tick)

    def _now(self) -> float:
        return self.get_clock().now().nanoseconds * 1e-9

    # ---------------------------------------------------------------- inputs
    def _on_state(self, msg: RobotState) -> None:
        self._active = msg.active_task_id
        self._blocked = msg.safety.latched or msg.mode in (
            RobotState.MODE_SAFE,
            RobotState.MODE_FAULT,
            RobotState.MODE_OFFLINE,
        )
        if self._claimed and self._active == self._claimed:
            self._claimed = None  # the executor took it; it is a normal task now

    def _on_lease(self, msg: String) -> None:
        lease = decode(msg.data)
        if lease is None:
            self.get_logger().warning("dropped an unparseable lease frame")
            return
        self._ledger[lease.task_id] = merge(self._ledger.get(lease.task_id), lease)
        # Somebody outbid us on a task we thought we had taken.
        if self._claimed == lease.task_id and lease.holder != self._robot_id:
            self.get_logger().warning(f"claim on {lease.task_id} lost to {lease.holder}")
            self._claimed = None

    # --------------------------------------------------------------- outputs
    def _held(self) -> str:
        return self._active or (self._claimed or "")

    def _renew(self) -> None:
        """Republish the lease for whatever this robot is holding.

        A blocked robot renews nothing. That is the handover trigger: the
        latched safe state of T-083 releases the work within one TTL instead of
        leaving it stranded on a robot that has stopped.
        """
        task_id = self._held()
        if not task_id or self._blocked:
            return
        now = self._now()
        lease = claim(self._ledger.get(task_id), task_id, self._robot_id, now, self._ttl_s)
        if lease is None:
            return  # somebody else holds it and is alive; do not fight them
        self._ledger[task_id] = lease
        self._renew_pub.publish(String(data=encode(lease)))

    def _tick(self) -> None:
        now = self._now()

        if self._claimed and now - self._claimed_at > self._ttl_s:
            self.get_logger().warning(
                f"executor never started {self._claimed}; releasing the claim"
            )
            self._claimed = None

        if self._blocked or self._held():
            return

        task_id = claimable(self._ledger, now, self._robot_id, self._peers, self._stagger_s)
        if task_id is None:
            return
        lease = claim(self._ledger.get(task_id), task_id, self._robot_id, now, self._ttl_s)
        if lease is None:
            return
        self._ledger[task_id] = lease
        self._claimed = task_id
        self._claimed_at = now
        # RELIABLE: a dropped claim is a task nobody owns.
        self._claim_pub.publish(String(data=encode(lease)))
        self.get_logger().warning(f"took over {task_id} at epoch {lease.epoch}")


def main(args=None) -> None:
    rclpy.init(args=args)
    node = LeaseAgent()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
