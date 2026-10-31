# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Software view of the L0 safety chain (NEML_SPEC.md SS5.1).
# This message NEVER replaces the hardware relay: it reports, it does not cut
# power. Published on the `state` QoS class (SS17.2) so late joiners get it.

uint8 REASON_NONE=0
uint8 REASON_ESTOP=1              # mushroom button opened the NC loop
uint8 REASON_WATCHDOG_TIMEOUT=2   # heartbeat older than the configured timeout
uint8 REASON_OVERCURRENT=3        # body current above SS13.3 limits.body_current_a_max
uint8 REASON_OVERTEMP=4           # body temperature above SS13.3 limits.body_temp_c_max
uint8 REASON_LINK_LOSS=5          # swarm link lost (T-083)
uint8 REASON_OPERATOR=6           # operator requested stop

std_msgs/Header header            # stamp: evaluation time, frame_id: base_link
bool estop_engaged                # true while the e-stop loop reads open
bool watchdog_ok                  # true while a heartbeat was seen within the timeout
float64 heartbeat_age_s           # seconds since the last heartbeat; +inf if never seen
bool latched                      # true while the software latch holds the stop
uint8 reason                      # one of REASON_*; the cause that latched the stop
builtin_interfaces/Time latched_at  # when the latch closed; zero while not latched
bool motors_enabled               # false whenever `latched` is true
bool reset_required               # true until an operator calls the reset service
