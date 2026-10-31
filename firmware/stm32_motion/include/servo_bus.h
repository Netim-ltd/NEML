// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// NEML stm32_motion - Feetech STS3215 bus packets (SPEC 13.3 actuators).
//
// Packet building and parsing only: no HAL, no UART, no state. main.c owns the
// half-duplex UART and its DMA; this file just fills a caller supplied buffer,
// so the framing and the checksum are covered by the host test.
//
// WARNING: the register map below is the Feetech STS series datasheet. Verify it
// against a single servo on the bench before the first 16 joint power-on
// (T-070 / T-072). A wrong register address here writes garbage into a servo.

#ifndef NEML_SERVO_BUS_H
#define NEML_SERVO_BUS_H

#include <stddef.h>
#include <stdint.h>

#include "neml_limits.h"

#define STS_BROADCAST_ID    0xFEu
#define STS_INST_READ       0x02u
#define STS_INST_WRITE      0x03u
#define STS_INST_SYNC_WRITE 0x83u

#define STS_REG_TORQUE_ENABLE 0x28u  // 40
#define STS_REG_GOAL_POSITION 0x2Au  // 42, u16 LE, then goal time (44), goal speed (46)
#define STS_REG_TORQUE_LIMIT  0x30u  // 48, u16 LE, per mille of stall torque
#define STS_REG_PRESENT_POS   0x38u  // 56, start of the 8 byte feedback block

// Feedback block read from STS_REG_PRESENT_POS: position, speed, load, voltage,
// temperature.
#define STS_FEEDBACK_LEN 8u

// 4096 counts over 360 degrees.
#define STS_COUNTS_PER_REV 4096.0f
#define STS_COUNTS_PER_RAD (STS_COUNTS_PER_REV / 6.28318531f)
#define STS_CENTER_COUNT   2048

// SPEC 5.1: the compile time torque limit is pushed into the servo's own current
// limiter as well, so the ceiling survives even a bug in this firmware. Per
// mille of the SPEC 13.3 stall torque.
#define STS_TORQUE_LIMIT_PERMILLE \
    ((uint16_t)((LIMIT_JOINT_TORQUE_MNM * 1000) / STS3215_STALL_TORQUE_MNM))
_Static_assert(STS_TORQUE_LIMIT_PERMILLE > 0 && STS_TORQUE_LIMIT_PERMILLE < 1000,
               "servo torque limit must be a real fraction of stall torque");

// Longest packet we ever build: sync write of position + time + speed (6 bytes)
// for every joint.
// Frame overhead: 0xFF 0xFF, id, len, instruction, start address, data length,
// checksum.
#define STS_SYNC_WRITE_PAYLOAD 6u
#define STS_TX_BUF_SIZE (8u + (STS_SYNC_WRITE_PAYLOAD + 1u) * NEML_JOINT_COUNT)

// Unit conversion. Out of range values saturate: a servo count is a physical
// position, there is no wrapping behaviour that would be safe here.
uint16_t servo_rad_to_count(float rad);
float    servo_count_to_rad(uint16_t count);
uint16_t servo_rads_to_speed(float rads);

// Sync write of goal position and goal speed to every joint. ids[] and the two
// arrays are NEML_JOINT_COUNT long. Returns the packet length, or 0 if buf is
// too small.
size_t servo_build_sync_goal(uint8_t *buf, size_t cap, const uint8_t *ids,
                             const float *pos_rad, const float *vel_rads);

// Single servo read of the feedback block. Returns the packet length, or 0.
size_t servo_build_read_feedback(uint8_t *buf, size_t cap, uint8_t id);

// Broadcast write of the torque limit and torque enable. Called once at startup,
// before any motion is allowed.
size_t servo_build_torque_limit(uint8_t *buf, size_t cap);
size_t servo_build_torque_enable(uint8_t *buf, size_t cap, uint8_t on);

// Parse a status packet. Returns 1 and fills *out on a valid, checksum correct
// feedback block from id; returns 0 otherwise. Never reads past len.
typedef struct {
    uint16_t position;
    int16_t  speed;
    int16_t  load;
    uint8_t  voltage_dv;   // decivolts
    uint8_t  temperature_c;
} servo_feedback_t;

int servo_parse_feedback(const uint8_t *buf, size_t len, uint8_t id,
                         servo_feedback_t *out);

#endif  // NEML_SERVO_BUS_H
