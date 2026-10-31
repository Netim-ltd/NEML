// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// NEML hard limits - COMPILE TIME ONLY. NEML_SPEC.md 5.1 and 13.3.
//
// One copy for all three MCUs. stm32_motion enforces the torque and velocity
// limits, esp32_aux enforces the current and temperature ones; they are the same
// numbers from the same SPEC 13.3 block, so they live in one file and cannot
// drift apart across two separately flashed binaries.
//
// These are not configuration. There is no runtime path that may raise them:
// no ROS parameter, no topic, no service, no flash cell, no micro-ROS message,
// no genome field. SPEC 13.3 puts the `limits` block outside the evolution loop
// ("L4 DEGISTIREMEZ - kod ile korunur") and this file is where that is enforced:
// changing a limit means editing this header, rebuilding, and a human running
// `make flash` behind a Level 4 approval (SPEC 5.2, SPEC 5.4 firmware.flash).
//
// If you are here to make the robot stronger or faster: you are in the wrong
// file. Fix the mechanism, not the limit.

#ifndef NEML_LIMITS_H
#define NEML_LIMITS_H

// SPEC 5.1, verbatim. Do not rename it, do not turn it into a variable.
#define MAX_TORQUE_NM 2.5f

// SPEC 13.3 limits.joint_velocity_rads_max.
#define MAX_JOINT_VEL_RADS 6.0f

// Integer mirrors of the SPEC 13.3 `limits` block, in milli-units, so the static
// assertions below are plain integer comparisons.
#define LIMIT_JOINT_TORQUE_MNM   2500   // limits.joint_torque_nm_max      = 2.5
#define LIMIT_JOINT_VEL_MRADS    6000   // limits.joint_velocity_rads_max  = 6.0
#define LIMIT_BODY_CURRENT_MA   20000   // limits.body_current_a_max       = 20.0
#define LIMIT_BODY_TEMP_MC      70000   // limits.body_temp_c_max          = 70.0

_Static_assert((int)(MAX_TORQUE_NM * 1000.0f) == LIMIT_JOINT_TORQUE_MNM,
               "MAX_TORQUE_NM drifted from NEML_SPEC 13.3 limits.joint_torque_nm_max");
_Static_assert((int)(MAX_JOINT_VEL_RADS * 1000.0f) == LIMIT_JOINT_VEL_MRADS,
               "MAX_JOINT_VEL_RADS drifted from NEML_SPEC 13.3 limits.joint_velocity_rads_max");

// SPEC 13.3 actuators: sts3215, stall_torque_nm 2.9. A firmware limit at or
// above stall torque limits nothing.
#define STS3215_STALL_TORQUE_MNM 2900
_Static_assert(LIMIT_JOINT_TORQUE_MNM < STS3215_STALL_TORQUE_MNM,
               "torque limit is at or above the STS3215 stall torque");

// SPEC 13.3 morphology.total_dof = 16 = actuators.count.
#define NEML_JOINT_COUNT 16
_Static_assert(NEML_JOINT_COUNT == 16, "NEML_SPEC 13.3 morphology.total_dof = 16");

// Joint temperature ceiling used by the control loop, from the same limits block.
#define MAX_JOINT_TEMP_C ((float)LIMIT_BODY_TEMP_MC / 1000.0f)

#endif  // NEML_LIMITS_H
