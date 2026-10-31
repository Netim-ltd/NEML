# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Depth camera pipeline for the realsense d405 (NEML_SPEC.md SS13.3, 15 Hz).

The pipeline has exactly two outputs and the split is the SS17.2 rule:

  telemetry/obstacle_distance  a single float, always on, costs nothing on the
                               swarm link. This is what the brain and the gait
                               actually consume.

  camera/image/compressed      JPEG, published ONLY while somebody is
                               subscribed and no faster than max_rate_hz. The
                               raw colour and depth images are subscribed
                               locally and are never re-published anywhere.

There is deliberately no raw image publisher in this node. Adding one would
put uncompressed frames on the swarm network, which SS17.2 forbids.
"""

import cv2
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)
from sensor_msgs.msg import CompressedImage, Image
from std_msgs.msg import Float32

from neml_perception.gate import nearest_obstacle_m, should_send

# SS17.2 QoS table.
TELEMETRY_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)
CAMERA_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)


class CameraGate(Node):
    def __init__(self) -> None:
        super().__init__("camera_gate")

        self.declare_parameter("depth_topic", "camera/depth/image_raw")
        self.declare_parameter("color_topic", "camera/color/image_raw")
        self.declare_parameter("compressed_topic", "camera/image/compressed")
        self.declare_parameter("obstacle_topic", "telemetry/obstacle_distance")
        self.declare_parameter("max_rate_hz", 2.0)
        self.declare_parameter("jpeg_quality", 60)
        self.declare_parameter("min_valid_m", 0.07)
        self.declare_parameter("max_valid_m", 3.0)
        self.declare_parameter("roi_fraction", 0.5)

        self._bridge = CvBridge()
        self._last_sent_s: float | None = None

        self._obstacle_pub = self.create_publisher(
            Float32, self.get_parameter("obstacle_topic").value, TELEMETRY_QOS
        )
        self._compressed_pub = self.create_publisher(
            CompressedImage, self.get_parameter("compressed_topic").value, CAMERA_QOS
        )

        self.create_subscription(
            Image, self.get_parameter("depth_topic").value, self._on_depth, CAMERA_QOS
        )
        self.create_subscription(
            Image, self.get_parameter("color_topic").value, self._on_color, CAMERA_QOS
        )

        self.get_logger().info(
            "camera_gate up: raw frames stay on the robot; compressed frames "
            f"only while subscribed, capped at "
            f"{self.get_parameter('max_rate_hz').value} Hz (SS17.2)."
        )

    def _now(self) -> float:
        return self.get_clock().now().nanoseconds * 1e-9

    def _on_depth(self, msg: Image) -> None:
        depth = self._bridge.imgmsg_to_cv2(msg, desired_encoding="passthrough")
        if msg.encoding == "16UC1":
            # realsense ships millimetres as uint16; SI everywhere else.
            depth = depth.astype("float32") * 1e-3
        out = Float32()
        out.data = nearest_obstacle_m(
            depth,
            min_valid_m=self.get_parameter("min_valid_m").value,
            max_valid_m=self.get_parameter("max_valid_m").value,
            roi_fraction=self.get_parameter("roi_fraction").value,
        )
        self._obstacle_pub.publish(out)

    def _on_color(self, msg: Image) -> None:
        now = self._now()
        if not should_send(
            self._compressed_pub.get_subscription_count(),
            now,
            self._last_sent_s,
            self.get_parameter("max_rate_hz").value,
        ):
            return
        frame = self._bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        quality = int(self.get_parameter("jpeg_quality").value)
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not ok:
            self.get_logger().warning("jpeg encode failed, frame dropped")
            return
        out = CompressedImage()
        out.header = msg.header
        out.format = "jpeg"
        out.data = buf.tobytes()
        self._compressed_pub.publish(out)
        self._last_sent_s = now


def main(args=None) -> None:
    rclpy.init(args=args)
    node = CameraGate()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
