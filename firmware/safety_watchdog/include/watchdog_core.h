// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// NEML L0 safety watchdog - decision logic only (NEML_SPEC.md 5.1, T-071).
//
// No register access and no AVR headers live here, so test/test_watchdog_core.c
// runs this exact code on a host compiler. src/main.c owns the hardware; this
// file answers one question: "may the motor relay be energised right now?".

#ifndef NEML_WATCHDOG_CORE_H
#define NEML_WATCHDOG_CORE_H

#include <stdint.h>

// SPEC 5.1: the main controller sends a heartbeat every 50 ms; the relay opens
// if 150 ms pass without one. Both numbers are the contract, not tuning knobs.
#define HB_PERIOD_MS    50u
#define HB_TIMEOUT_MS  150u

// An edge closer than this is not the 50 ms heartbeat: it is a ringing, shorted
// or spoofed line. While armed that is a fault, because a noisy input must never
// be able to hold the motor relay closed - and a plain "ignore it" filter cannot
// reject a fast periodic signal, it only decimates it. The heartbeat pin carries
// an RC glitch filter in hardware (see README) so real edges never land here.
#define HB_MIN_GAP_MS   20u

// Consecutive plausible heartbeats required before the relay is energised for
// the first time. Boot state is always "motion inhibited".
#define HB_ARM_EDGES     3u

typedef enum {
    WD_DISARMED = 0,  // boot / no healthy heartbeat yet - relay OPEN
    WD_ARMED    = 1,  // heartbeat healthy - relay CLOSED, motion allowed
    WD_TRIPPED  = 2   // timeout, bad heartbeat or firmware hang - relay OPEN, latched
} wd_state_t;

typedef struct {
    wd_state_t state;
    uint16_t   since_hb_ms;  // saturating
    uint8_t    good_edges;
} wd_t;

// latched_fault != 0 boots straight into WD_TRIPPED. main.c passes the WDRF flag
// here: a firmware hang must not be recoverable by rebooting.
static inline void wd_init(wd_t *w, uint8_t latched_fault)
{
    w->state       = latched_fault ? WD_TRIPPED : WD_DISARMED;
    w->since_hb_ms = HB_TIMEOUT_MS;   // nothing heard yet
    w->good_edges  = 0u;
}

// One edge on the heartbeat input.
static inline void wd_heartbeat(wd_t *w)
{
    if (w->state == WD_TRIPPED) {
        return;                       // latched: only a reset re-arms
    }
    if (w->since_hb_ms < HB_MIN_GAP_MS) {
        w->good_edges = 0u;           // implausibly early - do not refresh
        if (w->state == WD_ARMED) {
            w->state = WD_TRIPPED;    // ... and while armed, fail safe
        }
        return;
    }
    w->since_hb_ms = 0u;
    if (w->good_edges < HB_ARM_EDGES) {
        w->good_edges++;
    }
    if (w->state == WD_DISARMED && w->good_edges >= HB_ARM_EDGES) {
        w->state = WD_ARMED;
    }
}

// One 1 kHz tick. Called from the timer ISR so the trip latency is one tick.
static inline void wd_tick_1ms(wd_t *w)
{
    if (w->since_hb_ms < UINT16_MAX) {
        w->since_hb_ms++;
    }
    if (w->since_hb_ms >= HB_TIMEOUT_MS) {
        if (w->state == WD_ARMED) {
            w->state = WD_TRIPPED;    // SPEC 5.1 / T-071
        }
        w->good_edges = 0u;
    }
}

static inline uint8_t wd_relay_on(const wd_t *w)
{
    return (uint8_t)(w->state == WD_ARMED);
}

#endif  // NEML_WATCHDOG_CORE_H
