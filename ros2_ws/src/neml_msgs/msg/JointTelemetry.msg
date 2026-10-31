# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Per-joint measurements for the 16 sts3215 actuators (NEML_SPEC.md SS13.3).
# All arrays are parallel to `name` and share its length.
# Published on the `telemetry` QoS class (SS17.2).

std_msgs/Header header       # stamp: sample time, frame_id: base_link
string[] name                # joint names, e.g. "fl_hip_yaw"; 16 entries
float64[] position           # joint angle, radians
float64[] velocity           # joint angular velocity, radians per second
float64[] effort             # joint torque, newton-metres
float64[] temperature_c      # actuator case temperature, degrees Celsius
float64[] current_a          # actuator current from the ina226 rails, amperes
