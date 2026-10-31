// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// NEML stm32_motion - 1 kHz control step. See include/control.h.

#include "control.h"

static float clampf(float v, float lim)
{
    if (v > lim) {
        return lim;
    }
    if (v < -lim) {
        return -lim;
    }
    return v;
}

void control_init(control_t *c)
{
    for (int i = 0; i < NEML_JOINT_COUNT; i++) {
        c->cmd.position_rad[i]     = 0.0f;
        c->cmd.velocity_rads[i]    = 0.0f;
        c->state[i].position_rad   = 0.0f;
        c->state[i].velocity_rads  = 0.0f;
        c->state[i].torque_nm      = 0.0f;
        c->state[i].temperature_c  = 0.0f;
        c->out_torque_nm[i]        = 0.0f;
        c->out_velocity_rads[i]    = 0.0f;
        c->out_position_rad[i]     = 0.0f;
    }
    // Bench-tuned starting point. Hardware never matches the model: these are
    // the calibration knobs, the limits above them are not.
    c->kp         = 4.0f;
    c->kd         = 0.2f;
    c->cmd_age_ms = CMD_TIMEOUT_MS;   // nothing received yet -> start limp
    c->faults     = CTRL_FAULT_NO_COMMAND;
    c->latched    = 0u;
}

void control_set_command(control_t *c, const joint_cmd_t *cmd)
{
    c->cmd        = *cmd;
    c->cmd_age_ms = 0u;
}

void control_tick(control_t *c, uint8_t estop_open)
{
    if (c->cmd_age_ms < CMD_TIMEOUT_MS) {
        c->cmd_age_ms++;
    }
    if (estop_open) {
        c->faults  |= CTRL_FAULT_ESTOP;
        c->latched |= CTRL_FAULT_ESTOP;
    }
}

void control_step(control_t *c)
{
    // Keep the sticky bits, drop last tick's transient ones, then re-evaluate.
    uint8_t faults = (uint8_t)(c->faults & (CTRL_FAULT_TICK_OVERRUN | c->latched));

    const uint8_t no_command = (uint8_t)(c->cmd_age_ms >= CMD_TIMEOUT_MS);
    if (no_command) {
        faults |= CTRL_FAULT_NO_COMMAND;
    }

    // Pass 1: decide the safety state across every joint first. A fault found on
    // joint 15 must not leave joint 0 holding a torque command issued earlier in
    // the same tick.
    for (int i = 0; i < NEML_JOINT_COUNT; i++) {
        // SPEC 13.3 limits.body_temp_c_max. Over temperature is measured per
        // joint but critical for the whole robot: it latches and L0 takes the
        // power away.
        if (c->state[i].temperature_c > MAX_JOINT_TEMP_C) {
            faults     |= CTRL_FAULT_OVER_TEMP;
            c->latched |= CTRL_FAULT_OVER_TEMP;
        }
    }

    const uint8_t safe_state = (uint8_t)(no_command || (faults & CTRL_FAULT_CRITICAL) ||
                                         (c->latched & CTRL_FAULT_CRITICAL));

    // Pass 2: drive.
    for (int i = 0; i < NEML_JOINT_COUNT; i++) {
        const joint_state_t *s = &c->state[i];

        if (safe_state) {
            // Safe state: hold where we are, demand nothing. Driving towards a
            // stale target would be worse than standing still, and L0 is what
            // actually removes the power.
            c->out_torque_nm[i]     = 0.0f;
            c->out_velocity_rads[i] = 0.0f;
            c->out_position_rad[i]  = s->position_rad;
            continue;
        }

        // SPEC 13.3 limits.joint_velocity_rads_max - clamped before it is used,
        // so an out of range command cannot reach the actuator even for one tick.
        const float v_cmd = clampf(c->cmd.velocity_rads[i], MAX_JOINT_VEL_RADS);
        if (v_cmd != c->cmd.velocity_rads[i]) {
            faults |= CTRL_FAULT_VEL_CLAMPED;
        }

        const float pos_err = c->cmd.position_rad[i] - s->position_rad;
        const float vel_err = v_cmd - s->velocity_rads;
        const float torque  = c->kp * pos_err + c->kd * vel_err;

        // SPEC 5.1 MAX_TORQUE_NM. This is the only place a torque leaves this
        // module, and it is clamped on the way out. No runtime path may raise it.
        const float t_out = clampf(torque, MAX_TORQUE_NM);
        if (t_out != torque) {
            faults |= CTRL_FAULT_TORQUE_CLAMPED;
        }

        c->out_torque_nm[i]     = t_out;
        c->out_velocity_rads[i] = v_cmd;
        c->out_position_rad[i]  = c->cmd.position_rad[i];
    }

    c->faults = faults;
}
