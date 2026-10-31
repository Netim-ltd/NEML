// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// NEML stm32_motion - Feetech STS3215 bus packets. See include/servo_bus.h.
//
// Frame: FF FF <id> <len> <instruction> <params...> <checksum>
//   len      = number of params + 2
//   checksum = ~(id + len + instruction + sum(params))

#include "servo_bus.h"

#define STS_HEADER_LEN 4u   // FF FF id len

static uint8_t checksum(const uint8_t *frame, size_t len)
{
    uint8_t sum = 0u;
    for (size_t i = 2u; i + 1u < len; i++) {   // skip the two header bytes
        sum = (uint8_t)(sum + frame[i]);
    }
    return (uint8_t)~sum;
}

static size_t frame_begin(uint8_t *buf, uint8_t id, uint8_t nparams, uint8_t instr)
{
    buf[0] = 0xFFu;
    buf[1] = 0xFFu;
    buf[2] = id;
    buf[3] = (uint8_t)(nparams + 2u);
    buf[4] = instr;
    return 5u;
}

static size_t frame_end(uint8_t *buf, size_t n)
{
    buf[n] = checksum(buf, n + 1u);
    return n + 1u;
}

static void put_u16_le(uint8_t *p, uint16_t v)
{
    p[0] = (uint8_t)(v & 0xFFu);
    p[1] = (uint8_t)(v >> 8);
}

static uint16_t get_u16_le(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}

// STS feedback uses sign-magnitude, not two's complement.
static int16_t sts_signed(uint16_t v, unsigned sign_bit)
{
    const uint16_t mask = (uint16_t)((1u << sign_bit) - 1u);
    const int16_t  mag  = (int16_t)(v & mask);
    return (v & (1u << sign_bit)) ? (int16_t)-mag : mag;
}

uint16_t servo_rad_to_count(float rad)
{
    const float c = (float)STS_CENTER_COUNT + rad * STS_COUNTS_PER_RAD;
    if (c <= 0.0f) {
        return 0u;
    }
    if (c >= 4095.0f) {
        return 4095u;
    }
    return (uint16_t)c;
}

float servo_count_to_rad(uint16_t count)
{
    return ((float)count - (float)STS_CENTER_COUNT) / STS_COUNTS_PER_RAD;
}

uint16_t servo_rads_to_speed(float rads)
{
    float s = rads * STS_COUNTS_PER_RAD;
    if (s < 0.0f) {
        s = -s;
    }
    if (s >= 4095.0f) {
        return 4095u;
    }
    // On this servo family goal speed 0 means "as fast as you can". A zeroed
    // velocity command therefore has to become the slowest legal value, not the
    // fastest one, or the safe state turns into a full speed move.
    const uint16_t v = (uint16_t)s;
    return (v == 0u) ? 1u : v;
}

size_t servo_build_sync_goal(uint8_t *buf, size_t cap, const uint8_t *ids,
                             const float *pos_rad, const float *vel_rads)
{
    const uint8_t per   = (uint8_t)STS_SYNC_WRITE_PAYLOAD;
    const uint8_t nparm = (uint8_t)(2u + (per + 1u) * NEML_JOINT_COUNT);
    const size_t  total = (size_t)nparm + 6u;

    if (cap < total) {
        return 0u;
    }

    size_t n = frame_begin(buf, STS_BROADCAST_ID, nparm, STS_INST_SYNC_WRITE);
    buf[n++] = STS_REG_GOAL_POSITION;
    buf[n++] = per;

    for (int i = 0; i < NEML_JOINT_COUNT; i++) {
        buf[n++] = ids[i];
        put_u16_le(&buf[n], servo_rad_to_count(pos_rad[i]));
        n += 2u;
        put_u16_le(&buf[n], 0u);                                // goal time: unused
        n += 2u;
        put_u16_le(&buf[n], servo_rads_to_speed(vel_rads[i]));  // SPEC 13.3 velocity limit
        n += 2u;
    }

    return frame_end(buf, n);
}

size_t servo_build_read_feedback(uint8_t *buf, size_t cap, uint8_t id)
{
    if (cap < 8u) {
        return 0u;
    }
    size_t n = frame_begin(buf, id, 2u, STS_INST_READ);
    buf[n++] = STS_REG_PRESENT_POS;
    buf[n++] = (uint8_t)STS_FEEDBACK_LEN;
    return frame_end(buf, n);
}

size_t servo_build_torque_limit(uint8_t *buf, size_t cap)
{
    if (cap < 9u) {
        return 0u;
    }
    size_t n = frame_begin(buf, STS_BROADCAST_ID, 3u, STS_INST_WRITE);
    buf[n++] = STS_REG_TORQUE_LIMIT;
    put_u16_le(&buf[n], STS_TORQUE_LIMIT_PERMILLE);
    n += 2u;
    return frame_end(buf, n);
}

size_t servo_build_torque_enable(uint8_t *buf, size_t cap, uint8_t on)
{
    if (cap < 8u) {
        return 0u;
    }
    size_t n = frame_begin(buf, STS_BROADCAST_ID, 2u, STS_INST_WRITE);
    buf[n++] = STS_REG_TORQUE_ENABLE;
    buf[n++] = on ? 1u : 0u;
    return frame_end(buf, n);
}

int servo_parse_feedback(const uint8_t *buf, size_t len, uint8_t id,
                         servo_feedback_t *out)
{
    const size_t expect = STS_HEADER_LEN + 1u + STS_FEEDBACK_LEN + 1u;  // + error byte
    if (len < expect) {
        return 0;
    }
    if (buf[0] != 0xFFu || buf[1] != 0xFFu || buf[2] != id) {
        return 0;
    }
    if (buf[3] != (uint8_t)(STS_FEEDBACK_LEN + 2u)) {
        return 0;
    }
    if (checksum(buf, expect) != buf[expect - 1u]) {
        return 0;
    }

    const uint8_t *p = &buf[5];   // past the error byte
    out->position      = get_u16_le(&p[0]);
    out->speed         = sts_signed(get_u16_le(&p[2]), 15u);
    out->load          = sts_signed(get_u16_le(&p[4]), 10u);
    out->voltage_dv    = p[6];
    out->temperature_c = p[7];
    return 1;
}
