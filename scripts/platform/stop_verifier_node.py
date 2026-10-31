# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Separate-host ROS 2 verifier for a measured stop recovery only."""

from __future__ import annotations

import json
import math
import os
from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path

import rclpy
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from neml_brain.platform.feedback import attest_recovery
from neml_brain.platform.postcondition import MotionSample, stable_stop
from neml_msgs.msg import JointTelemetry, RobotState
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

TELEMETRY_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)
STATE_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)


class StopVerifier(Node):
    def __init__(self) -> None:
        super().__init__("stop_outcome_verifier")
        self.declare_parameter("joint_topic", "telemetry/joint_states")
        self.declare_parameter("state_topic", "state/robot")
        self.identity = {
            "tenant_id": os.environ["NEML_TENANT_ID"],
            "domain_id": os.environ["NEML_DOMAIN_ID"],
            "robot_id": os.environ["NEML_ROBOT_ID"],
            "verifier_id": os.environ["NEML_VERIFIER_ID"],
        }
        self.inbox = Path(os.environ["NEML_VERIFIER_REPORT_DIR"]).resolve()
        self.outbox = Path(os.environ["NEML_VERIFIED_REPORT_DIR"]).resolve()
        self.outbox.mkdir(parents=True, exist_ok=True)
        self.robot_public = bytes.fromhex(
            Path(os.environ["NEML_ROBOT_PUBLIC_KEY_FILE"]).read_text(encoding="utf-8").strip()
        )
        self.verifier_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(
            Path(os.environ["NEML_VERIFIER_PRIVATE_KEY_FILE"]).read_text(
                encoding="utf-8"
            ).strip()
        ))
        self.samples: deque[MotionSample] = deque(maxlen=200)
        self.last_joint: tuple[datetime, float] | None = None
        self.create_subscription(JointTelemetry, str(self.get_parameter("joint_topic").value),
                                 self._on_joint, TELEMETRY_QOS)
        self.create_subscription(RobotState, str(self.get_parameter("state_topic").value),
                                 self._on_state, STATE_QOS)
        self.create_timer(0.2, self._tick)

    def _on_joint(self, message: JointTelemetry) -> None:
        if (len(message.name) != 16 or len(set(message.name)) != 16
                or len(message.velocity) != 16
                or any(not math.isfinite(v) for v in message.velocity)):
            self.last_joint = None
            return
        self.last_joint = (datetime.now(UTC), max(abs(v) for v in message.velocity))

    def _on_state(self, message: RobotState) -> None:
        now = datetime.now(UTC)
        if message.robot_id != self.identity["robot_id"] or self.last_joint is None:
            return
        joint_at, joint_speed = self.last_joint
        if now - joint_at > timedelta(milliseconds=200):
            return
        body = message.twist.linear
        body_speed = math.sqrt(body.x * body.x + body.y * body.y + body.z * body.z)
        rotation = message.twist.angular
        body_rotation = math.sqrt(
            rotation.x * rotation.x + rotation.y * rotation.y + rotation.z * rotation.z
        )
        self.samples.append(MotionSample(now, joint_speed, body_speed, body_rotation))

    def _tick(self) -> None:
        now = datetime.now(UTC)
        for path in sorted(self.inbox.glob("*.json")):
            destination = self.outbox / path.name
            if destination.exists():
                continue
            try:
                if path.stat().st_size > 16 * 1024:
                    raise ValueError("report too large")
                report = json.loads(path.read_text(encoding="utf-8"))
                if any(report.get(key) != value for key, value in self.identity.items()):
                    raise ValueError("report identity mismatch")
                if report.get("recovery_action") != "stop":
                    continue  # Other actions need their own measured verifier.
                report_at = datetime.fromisoformat(report["occurred_at"])
                if (report_at.tzinfo is None
                        or not timedelta(0) <= now - report_at <= timedelta(seconds=30)):
                    raise ValueError("report is stale or from the future")
                attested = attest_recovery(
                    report, self.robot_public, self.verifier_key,
                    lambda _, at=report_at: stable_stop(self.samples, at, now),
                )
                temporary = destination.with_suffix(".tmp")
                temporary.write_text(json.dumps(attested, sort_keys=True), encoding="utf-8")
                os.replace(temporary, destination)
            except PermissionError:
                continue  # Wait for a full, fresh stationary window.
            except (KeyError, TypeError, ValueError, OSError) as exc:
                self.get_logger().warn(f"feedback report ignored: {type(exc).__name__}: {exc}")


def main() -> None:
    rclpy.init()
    node = StopVerifier()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
