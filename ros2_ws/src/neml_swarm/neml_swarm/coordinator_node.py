# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Swarm coordinator - the lab-side half of Faz 5 (NEML_SPEC.md T-082).

It keeps a view of every task lease on the fleet, notices when one expires, and
publishes an advisory plan naming who should pick the orphan up.

IT IS NOT A BROKER. It grants nothing and it owns nothing. The binding fact is
the lease (lease.py), and the robots take expired leases themselves
(lease_agent_node.py). Kill this process and handover still happens - all that
is lost is the fleet-wide view and the load balancing. That is deliberate:
SS17.2 runs the swarm over WiFi, and anything that must be reachable for work
to continue is the thing that stops the fleet when the link drops.

The plan is advisory for a second reason: a robot that has been partitioned off
has newer information about itself than this node does, and the lease epoch is
what settles the disagreement, not who published last.

ponytail: JSON over std_msgs/String, package-wide. Costs one parse per message
at a few Hz and saves a neml_msgs definition that T-084 would rewrite when it
freezes the task queue. Promote to a typed message then.
"""

import json

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

from neml_swarm.assignment import LINK_TIMEOUT_S, Task, alive_robots, reassign
from neml_swarm.lease import Lease, decode, expired_tasks, is_expired, merge

# SS17.2 QoS table. Every publisher and subscriber in this node uses the
# profile its topic class demands and nothing else.
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


class Coordinator(Node):
    def __init__(self) -> None:
        super().__init__("swarm_coordinator")

        self.declare_parameter("robots", ["r01"])
        self.declare_parameter("robot_state_topic", "state/robot")
        self.declare_parameter("tasks_topic", "swarm/tasks")
        self.declare_parameter("assignments_topic", "swarm/assignments")
        self.declare_parameter("heartbeat_topic", "swarm/coordinator_heartbeat")
        # SS17.2 classes: renewals are periodic telemetry (a lost one costs one
        # period), claims are commands (a lost one orphans a task).
        self.declare_parameter("lease_renew_topic", "/swarm/telemetry/lease")
        self.declare_parameter("lease_claim_topic", "/swarm/cmd/lease_claim")
        self.declare_parameter("robot_timeout_s", LINK_TIMEOUT_S)
        self.declare_parameter("check_rate_hz", 2.0)
        self.declare_parameter("heartbeat_rate_hz", 5.0)

        self._timeout_s = self.get_parameter("robot_timeout_s").value
        self._last_seen: dict[str, float] = {}
        self._tasks: list[Task] = []
        self._leases: dict[str, Lease] = {}
        self._last_plan: dict[str, str] = {}
        self._reported_expired: set[str] = set()

        state_topic = self.get_parameter("robot_state_topic").value
        for robot in self.get_parameter("robots").value:
            self.create_subscription(
                RobotState,
                f"/{robot}/{state_topic}",
                self._make_state_cb(robot),
                STATE_QOS,
            )

        self.create_subscription(
            String, self.get_parameter("tasks_topic").value, self._on_tasks, CMD_QOS
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
        self._plan_pub = self.create_publisher(
            String, self.get_parameter("assignments_topic").value, CMD_QOS
        )
        # The link guard on every robot watches this. Losing it is what starts
        # the T-083 two second safe-state transition.
        self._heartbeat_pub = self.create_publisher(
            String, self.get_parameter("heartbeat_topic").value, CMD_QOS
        )

        self.create_timer(
            1.0 / self.get_parameter("heartbeat_rate_hz").value, self._beat
        )
        self.create_timer(1.0 / self.get_parameter("check_rate_hz").value, self._check)

    def _now(self) -> float:
        return self.get_clock().now().nanoseconds * 1e-9

    def _make_state_cb(self, robot: str):
        def cb(msg: RobotState) -> None:
            # A robot that latched its safety stop is up but cannot work, so it
            # is not a handover target: treat it as gone for assignment.
            if msg.safety.latched or msg.mode in (RobotState.MODE_SAFE, RobotState.MODE_FAULT):
                self._last_seen.pop(robot, None)
                return
            self._last_seen[robot] = self._now()

        return cb

    def _on_tasks(self, msg: String) -> None:
        self._tasks = [
            Task(
                task_id=str(item["task_id"]),
                assigned_to=str(item.get("assigned_to", "")),
                priority=int(item.get("priority", 0)),
            )
            for item in json.loads(msg.data)
        ]

    def _on_lease(self, msg: String) -> None:
        """Renewals and claims fold into the same ledger - a claim is only a
        lease with a higher epoch, and merge() settles both."""
        lease = decode(msg.data)
        if lease is None:
            self.get_logger().warning("dropped an unparseable lease frame")
            return
        self._leases[lease.task_id] = merge(self._leases.get(lease.task_id), lease)
        self._reported_expired.discard(lease.task_id)

    def _beat(self) -> None:
        self._heartbeat_pub.publish(String(data=str(self._now())))

    def _owner(self, task: Task, now: float) -> str:
        """Who holds this task right now. An expired lease owns nothing, which
        is what turns a dropped robot's work into an orphan without anybody
        having to declare the robot dead."""
        lease = self._leases.get(task.task_id)
        if lease is None or is_expired(lease, now):
            return ""
        return lease.holder

    def _check(self) -> None:
        now = self._now()
        for task_id in expired_tasks(self._leases, now):
            if task_id not in self._reported_expired:
                self._reported_expired.add(task_id)
                holder = self._leases[task_id].holder
                self.get_logger().warning(f"lease expired: {task_id} was held by {holder}")

        owned = [Task(t.task_id, self._owner(t, now), t.priority) for t in self._tasks]
        alive = alive_robots(self._last_seen, now, self._timeout_s)
        plan = reassign(owned, alive)
        if plan == self._last_plan:
            return
        self._last_plan = plan
        if plan:
            self.get_logger().warning(f"handover advice: {plan} (alive: {sorted(alive)})")
        self._plan_pub.publish(String(data=json.dumps(plan, sort_keys=True)))


def main(args=None) -> None:
    rclpy.init(args=args)
    node = Coordinator()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
