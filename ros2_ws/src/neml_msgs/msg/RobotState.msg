# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Aggregate robot state. One publisher per robot, on the `state` QoS class
# (NEML_SPEC.md SS17.2: RELIABLE / TRANSIENT_LOCAL / KEEP_LAST(1)).

uint8 MODE_OFFLINE=0
uint8 MODE_IDLE=1
uint8 MODE_BUSY=2
uint8 MODE_SAFE=3            # latched safe state (SS5.1 / T-083)
uint8 MODE_FAULT=4

uint8 LEVEL_SIM=0            # SS5.2 deployment gates
uint8 LEVEL_BENCH=1
uint8 LEVEL_TETHERED=2
uint8 LEVEL_FREE=3
uint8 LEVEL_MANUFACTURE=4

std_msgs/Header header       # stamp: publish time, frame_id: map
string robot_id              # lab-unique id, e.g. "r01"
string genome_hash           # SS13.3 genome hash this stack was built from
uint8 mode                   # one of MODE_*
uint8 deployment_level       # one of LEVEL_*; currently granted level
string active_task_id        # empty string when no task is running
geometry_msgs/Pose pose      # base_link in the map frame; position metres, unit quaternion
geometry_msgs/Twist twist    # base_link velocity; linear m/s, angular rad/s
BatteryState battery         # pack state at the time of publishing
SafetyStatus safety          # safety chain state at the time of publishing
