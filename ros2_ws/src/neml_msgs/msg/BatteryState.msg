# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Pack state of the 4S LiPo described in NEML_SPEC.md SS13.3.
# All quantities are SI. Published on the `telemetry` QoS class (SS17.2).

std_msgs/Header header       # stamp: sample time (sim time in simulation), frame_id: battery link
float64 voltage_v            # pack terminal voltage, volts
float64 current_a            # pack current, amperes; negative while discharging
float64 charge_ah            # remaining charge, ampere-hours
float64 capacity_ah          # full-charge capacity, ampere-hours (SS13.3: 5.2 Ah nominal)
float64 percentage           # state of charge, 0.0 .. 1.0 (dimensionless)
float64 temperature_c        # hottest cell temperature, degrees Celsius
float64[] cell_voltage_v     # per-cell voltage, volts; length == cell_count
uint8 cell_count             # series cell count (SS13.3: 4)
bool bms_ok                  # false when the BMS reports any protection event
