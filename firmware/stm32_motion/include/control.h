// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// NEML stm32_motion - 1 kHz control step (NEML_SPEC.md 16/T-072).
//
// This translation unit touches no HAL, no peripheral and no global state, so
// test/test_stm32_motion.c runs the real limit enforcement on a host compiler.
// It contains no allocation, no division by a runtime value, no unbounded loop
// and no call that can block: everything here runs inside the 1 kHz ISR.

#ifndef NEML_CONTROL_H
#define NEML_CONTROL_H

#include <stdint.h>

#include "neml_limits.h"

// A command older than this is not a command. The robot-level rule is 2 s to a
// safe state (SPEC 16/T-083); at joint level we are far stricter, because the
// planner publishes at 100 Hz and ten missed messages already mean the link is
// gone.
#define CMD_TIMEOUT_MS 100u

#define CTRL_FAULT_TORQUE_CLAMPED 0x01u  // a joint asked for more than MAX_TORQUE_NM
#define CTRL_FAULT_VEL_CLAMPED    0x02u  // a joint asked for more than MAX_JOINT_VEL_RADS
#define CTRL_FAULT_OVER_TEMP      0x04u  // SPEC 13.3 limits.body_temp_c_max
#define CTRL_FAULT_NO_COMMAND     0x08u  // command older than CMD_TIMEOUT_MS
#define CTRL_FAULT_TICK_OVERRUN   0x10u  // the 1 kHz tick blew its budget
#define CTRL_FAULT_ESTOP          0x20u  // e-stop loop open (SPEC 5.1)
#define CTRL_FAULT_HEAP           0x40u  // something asked for memory after boot

// Faults that must bring the robot down through L0 rather than be reported and
// forgotten: main.c stops toggling the heartbeat while any of these is latched,
// and the ATmega328P opens the motor relay 150 ms later.
#define CTRL_FAULT_CRITICAL (CTRL_FAULT_OVER_TEMP | CTRL_FAULT_ESTOP)

typedef struct {
    float position_rad;
    float velocity_rads;
    float torque_nm;      // measured load, signed
    float temperature_c;
} joint_state_t;

typedef struct {
    float position_rad[NEML_JOINT_COUNT];
    float velocity_rads[NEML_JOINT_COUNT];
} joint_cmd_t;

typedef struct {
    joint_cmd_t   cmd;
    joint_state_t state[NEML_JOINT_COUNT];
    float         out_torque_nm[NEML_JOINT_COUNT];   // always within +/- MAX_TORQUE_NM
    float         out_velocity_rads[NEML_JOINT_COUNT];
    // What actually goes on the servo bus. In the safe state this is the
    // measured position, not the commanded one: a safe state must hold still,
    // not drive towards a stale target.
    float         out_position_rad[NEML_JOINT_COUNT];
    float         kp;          // calibration knobs - see README, tuned on the bench
    float         kd;
    uint32_t      cmd_age_ms;
    uint8_t       faults;      // this tick
    uint8_t       latched;     // sticky CTRL_FAULT_CRITICAL, cleared only by reset
} control_t;

void control_init(control_t *c);

// Copy a freshly received command in and reset its age. Called from the
// micro-ROS subscription callback with interrupts masked (see main.c).
void control_set_command(control_t *c, const joint_cmd_t *cmd);

// One 1 kHz tick: age the command, sample the e-stop line. estop_open != 0 means
// the e-stop loop is broken, i.e. the button is pressed.
void control_tick(control_t *c, uint8_t estop_open);

// One control step. Bounded by NEML_JOINT_COUNT, no allocation, no blocking.
void control_step(control_t *c);

#endif  // NEML_CONTROL_H
