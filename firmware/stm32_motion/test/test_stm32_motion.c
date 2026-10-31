// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Host test for the parts of stm32_motion that do not touch a register: the
// limit enforcement of NEML_SPEC.md 5.1 / 13.3 and the servo bus framing.
// Timing is proved on the bench (see README); this proves the arithmetic.
//
//   cmake -B build-test -DHOST_TESTS=ON && cmake --build build-test && ctest --test-dir build-test

#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "control.h"
#include "servo_bus.h"

static void step(control_t *c, uint8_t estop_open)
{
    control_tick(c, estop_open);
    control_step(c);
}

static uint8_t frame_checksum(const uint8_t *f, size_t len)
{
    uint8_t sum = 0u;
    for (size_t i = 2u; i + 1u < len; i++) {
        sum = (uint8_t)(sum + f[i]);
    }
    return (uint8_t)~sum;
}

static void test_limits_are_the_spec(void)
{
    // SPEC 5.1 verbatim, SPEC 13.3 limits block.
    assert(fabsf(MAX_TORQUE_NM - 2.5f) < 1e-6f);
    assert(fabsf(MAX_JOINT_VEL_RADS - 6.0f) < 1e-6f);
    assert(LIMIT_BODY_CURRENT_MA == 20000);
    assert(LIMIT_BODY_TEMP_MC == 70000);
    assert(NEML_JOINT_COUNT == 16);
    // The servo's own limiter carries the same ceiling.
    assert(STS_TORQUE_LIMIT_PERMILLE == (uint16_t)((2500 * 1000) / 2900));
}

static void test_torque_is_clamped(void)
{
    control_t c;
    control_init(&c);

    joint_cmd_t cmd;
    for (int i = 0; i < NEML_JOINT_COUNT; i++) {
        cmd.position_rad[i]  = 1000.0f;   // absurd: 1000 rad of position error
        cmd.velocity_rads[i] = 0.0f;
    }
    control_set_command(&c, &cmd);
    step(&c, 0);

    for (int i = 0; i < NEML_JOINT_COUNT; i++) {
        assert(c.out_torque_nm[i] <= MAX_TORQUE_NM);
        assert(c.out_torque_nm[i] >= -MAX_TORQUE_NM);
    }
    assert(c.faults & CTRL_FAULT_TORQUE_CLAMPED);

    // ... and in the other direction.
    for (int i = 0; i < NEML_JOINT_COUNT; i++) {
        cmd.position_rad[i] = -1000.0f;
    }
    control_set_command(&c, &cmd);
    step(&c, 0);
    for (int i = 0; i < NEML_JOINT_COUNT; i++) {
        assert(c.out_torque_nm[i] >= -MAX_TORQUE_NM);
    }
}

static void test_velocity_is_clamped(void)
{
    control_t c;
    control_init(&c);

    joint_cmd_t cmd;
    for (int i = 0; i < NEML_JOINT_COUNT; i++) {
        cmd.position_rad[i]  = 0.0f;
        cmd.velocity_rads[i] = (i & 1) ? 99.0f : -99.0f;
    }
    control_set_command(&c, &cmd);
    step(&c, 0);

    for (int i = 0; i < NEML_JOINT_COUNT; i++) {
        assert(fabsf(c.out_velocity_rads[i]) <= MAX_JOINT_VEL_RADS);
    }
    assert(c.faults & CTRL_FAULT_VEL_CLAMPED);
}

static void test_command_timeout_goes_limp(void)
{
    control_t c;
    control_init(&c);

    joint_cmd_t cmd;
    for (int i = 0; i < NEML_JOINT_COUNT; i++) {
        cmd.position_rad[i]  = 1.0f;
        cmd.velocity_rads[i] = 1.0f;
    }
    control_set_command(&c, &cmd);
    step(&c, 0);
    assert(!(c.faults & CTRL_FAULT_NO_COMMAND));
    assert(c.out_torque_nm[0] != 0.0f);

    for (unsigned t = 0; t < CMD_TIMEOUT_MS; t++) {
        step(&c, 0);
    }
    assert(c.faults & CTRL_FAULT_NO_COMMAND);
    for (int i = 0; i < NEML_JOINT_COUNT; i++) {
        assert(c.out_torque_nm[i] == 0.0f);
    }
}

static void test_estop_latches(void)
{
    control_t c;
    control_init(&c);

    joint_cmd_t cmd;
    for (int i = 0; i < NEML_JOINT_COUNT; i++) {
        cmd.position_rad[i]  = 1.0f;
        cmd.velocity_rads[i] = 1.0f;
    }
    control_set_command(&c, &cmd);

    step(&c, 1);                                  // e-stop loop open
    assert(c.latched & CTRL_FAULT_ESTOP);
    assert(c.out_torque_nm[0] == 0.0f);

    // Releasing the button must not restart the robot.
    for (int t = 0; t < 10; t++) {
        control_set_command(&c, &cmd);
        step(&c, 0);
        assert(c.latched & CTRL_FAULT_ESTOP);
        assert(c.out_torque_nm[0] == 0.0f);
    }
}

static void test_over_temperature_latches(void)
{
    control_t c;
    control_init(&c);

    joint_cmd_t cmd;
    for (int i = 0; i < NEML_JOINT_COUNT; i++) {
        cmd.position_rad[i]  = 1.0f;
        cmd.velocity_rads[i] = 1.0f;
    }
    control_set_command(&c, &cmd);
    c.state[7].temperature_c = MAX_JOINT_TEMP_C + 0.1f;   // SPEC 13.3 body_temp_c_max
    step(&c, 0);

    assert(c.latched & CTRL_FAULT_OVER_TEMP);
    for (int i = 0; i < NEML_JOINT_COUNT; i++) {
        assert(c.out_torque_nm[i] == 0.0f);
    }

    c.state[7].temperature_c = 25.0f;
    control_set_command(&c, &cmd);
    step(&c, 0);
    assert(c.out_torque_nm[0] == 0.0f);   // still latched
}

static void test_safe_state_holds_position(void)
{
    control_t c;
    control_init(&c);
    for (int i = 0; i < NEML_JOINT_COUNT; i++) {
        c.state[i].position_rad = 0.25f * (float)i;
    }
    step(&c, 0);   // no command yet -> safe state
    for (int i = 0; i < NEML_JOINT_COUNT; i++) {
        assert(c.out_position_rad[i] == c.state[i].position_rad);
    }
}

static void test_servo_units(void)
{
    // Round trip through servo counts, within one count.
    for (float rad = -3.0f; rad <= 3.0f; rad += 0.25f) {
        const float back = servo_count_to_rad(servo_rad_to_count(rad));
        assert(fabsf(back - rad) < (2.0f / STS_COUNTS_PER_RAD));
    }
    // Saturation, not wrap-around.
    assert(servo_rad_to_count(100.0f) == 4095u);
    assert(servo_rad_to_count(-100.0f) == 0u);

    // Goal speed 0 means "maximum speed" on this servo family, so a zeroed
    // velocity must never come out as 0.
    assert(servo_rads_to_speed(0.0f) != 0u);
    assert(servo_rads_to_speed(-1.0f) == servo_rads_to_speed(1.0f));
    assert(servo_rads_to_speed(MAX_JOINT_VEL_RADS) <= 4095u);
}

static void test_servo_packets(void)
{
    uint8_t  buf[STS_TX_BUF_SIZE];
    uint8_t  ids[NEML_JOINT_COUNT];
    float    pos[NEML_JOINT_COUNT];
    float    vel[NEML_JOINT_COUNT];

    for (int i = 0; i < NEML_JOINT_COUNT; i++) {
        ids[i] = (uint8_t)(i + 1);
        pos[i] = 0.1f * (float)i;
        vel[i] = 1.0f;
    }

    const size_t n = servo_build_sync_goal(buf, sizeof(buf), ids, pos, vel);
    assert(n == sizeof(buf));
    assert(buf[0] == 0xFFu && buf[1] == 0xFFu);
    assert(buf[2] == STS_BROADCAST_ID);
    assert(buf[4] == STS_INST_SYNC_WRITE);
    assert(buf[5] == STS_REG_GOAL_POSITION);
    assert(buf[6] == STS_SYNC_WRITE_PAYLOAD);
    assert(buf[3] == (uint8_t)(2u + (STS_SYNC_WRITE_PAYLOAD + 1u) * NEML_JOINT_COUNT + 2u));
    assert(buf[n - 1u] == frame_checksum(buf, n));

    // A buffer one byte short must be refused, not overrun.
    assert(servo_build_sync_goal(buf, sizeof(buf) - 1u, ids, pos, vel) == 0u);

    assert(servo_build_read_feedback(buf, sizeof(buf), 3u) == 8u);
    assert(buf[2] == 3u && buf[4] == STS_INST_READ && buf[5] == STS_REG_PRESENT_POS);
    assert(buf[7] == frame_checksum(buf, 8u));

    assert(servo_build_torque_limit(buf, sizeof(buf)) == 9u);
    assert(buf[5] == STS_REG_TORQUE_LIMIT);
    assert((uint16_t)(buf[6] | (buf[7] << 8)) == STS_TORQUE_LIMIT_PERMILLE);
}

static void test_servo_feedback_parse(void)
{
    // FF FF id len err pos(2) speed(2) load(2) volt temp csum
    uint8_t f[14] = {0xFFu, 0xFFu, 5u, 10u, 0u,
                     0x00u, 0x08u,          // position 2048 = centre
                     0x64u, 0x80u,          // speed -100 (sign-magnitude, bit 15)
                     0x2Cu, 0x05u,          // load -300 (sign-magnitude, bit 10)
                     120u,                  // 12.0 V
                     35u,                   // 35 C
                     0u};
    f[13] = frame_checksum(f, sizeof(f));

    servo_feedback_t fb;
    assert(servo_parse_feedback(f, sizeof(f), 5u, &fb) == 1);
    assert(fb.position == 2048u);
    assert(fb.speed == -100);
    assert(fb.load == -300);
    assert(fb.voltage_dv == 120u);
    assert(fb.temperature_c == 35u);
    assert(fabsf(servo_count_to_rad(fb.position)) < 1e-3f);

    // A corrupted byte must be rejected, not silently used as joint state.
    f[6] ^= 0x01u;
    assert(servo_parse_feedback(f, sizeof(f), 5u, &fb) == 0);
    f[6] ^= 0x01u;

    // Wrong id, short buffer.
    assert(servo_parse_feedback(f, sizeof(f), 6u, &fb) == 0);
    assert(servo_parse_feedback(f, 13u, 5u, &fb) == 0);
}

int main(void)
{
    test_limits_are_the_spec();
    test_torque_is_clamped();
    test_velocity_is_clamped();
    test_command_timeout_goes_limp();
    test_estop_latches();
    test_over_temperature_latches();
    test_safe_state_holds_position();
    test_servo_units();
    test_servo_packets();
    test_servo_feedback_parse();

    printf("stm32_motion: all assertions passed\n");
    return 0;
}
