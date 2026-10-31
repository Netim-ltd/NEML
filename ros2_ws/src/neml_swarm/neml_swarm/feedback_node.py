# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Robot-side ROS 2 skill outcome listener; writes signed recovery candidates."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import rclpy
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from neml_brain.platform.feedback import sign_report
from neml_brain.platform.recovery import RecoveryTracker, SkillOutcome
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

CMD_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)


class FeedbackNode(Node):
    def __init__(self) -> None:
        super().__init__("feedback_monitor")
        self.declare_parameter("outcome_topic", "state/skill_outcome")
        self.declare_parameter("verifier_id", "outcome-monitor-01")
        self.scope = {
            "tenant_id": os.environ["NEML_TENANT_ID"],
            "domain_id": os.environ["NEML_DOMAIN_ID"],
            "robot_id": os.environ["NEML_ROBOT_ID"],
            "robot_type": os.environ["NEML_ROBOT_TYPE"],
        }
        self.output_dir = Path(os.environ["NEML_EDGE_REPORT_DIR"]).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        key_data = Path(os.environ["NEML_DEVICE_PRIVATE_KEY_FILE"]).read_text(
            encoding="utf-8"
        ).strip()
        self.key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(key_data))
        self.tracker = RecoveryTracker()
        self.create_subscription(
            String, str(self.get_parameter("outcome_topic").value),
            self._on_outcome, CMD_QOS,
        )

    def _on_outcome(self, message: String) -> None:
        try:
            body = json.loads(message.data)
            if type(body["success"]) is not bool:
                raise ValueError("success must be boolean")
            if any(isinstance(value, bool) for value in body["features"]):
                raise ValueError("features must be numeric")
            outcome = SkillOutcome(
                task_id=str(body["task_id"]), operation=str(body["operation"]),
                action=str(body["action"]), success=body["success"],
                failure_class=str(body.get("failure_class", "")),
                features=tuple(float(value) for value in body["features"]),
                quality=float(body["quality"]),
                occurred_at=datetime.fromisoformat(body["occurred_at"]),
            )
            trace = self.tracker.observe(outcome)
            if trace is None:
                return
            report = {
                **self.scope, **trace, "report_id": str(uuid4()),
                "occurred_at": outcome.occurred_at.astimezone(UTC).isoformat(),
                "verifier_id": str(self.get_parameter("verifier_id").value),
            }
            report["robot_signature"] = sign_report(report, self.key)
            destination = self.output_dir / f"{report['report_id']}.json"
            temporary = destination.with_suffix(".tmp")
            temporary.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
            os.replace(temporary, destination)
        except (KeyError, TypeError, ValueError, OSError) as exc:
            self.get_logger().warn(f"learning outcome ignored: {type(exc).__name__}: {exc}")


def main() -> None:
    rclpy.init()
    node = FeedbackNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
