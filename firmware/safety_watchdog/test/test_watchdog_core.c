// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Host test for the L0 watchdog decision logic (NEML_SPEC.md 5.1, T-071).
// The scope test in docs/T-071_test_plani.md proves the timing on real silicon;
// this proves the state machine and runs anywhere.
//
//   make test
//   (or: cc -std=c11 -Iinclude test/test_watchdog_core.c -o t && ./t)

#include <assert.h>
#include <stdio.h>

#include "watchdog_core.h"

static void ticks(wd_t *w, unsigned n)
{
    while (n--) {
        wd_tick_1ms(w);
    }
}

static void arm(wd_t *w)
{
    for (unsigned i = 0; i < HB_ARM_EDGES; i++) {
        wd_heartbeat(w);
        ticks(w, HB_PERIOD_MS);
    }
}

int main(void)
{
    wd_t w;

    // 1. Boot state is relay OPEN, always.
    wd_init(&w, 0);
    assert(!wd_relay_on(&w));

    // 2. Three plausible heartbeats arm it. Two do not.
    wd_heartbeat(&w);
    ticks(&w, HB_PERIOD_MS);
    assert(!wd_relay_on(&w));
    wd_heartbeat(&w);
    ticks(&w, HB_PERIOD_MS);
    assert(!wd_relay_on(&w));
    wd_heartbeat(&w);
    assert(wd_relay_on(&w));

    // 3. T-071: survives 149 ms of silence, opens on the 150th millisecond.
    ticks(&w, HB_TIMEOUT_MS - 1u);
    assert(wd_relay_on(&w));
    ticks(&w, 1u);
    assert(!wd_relay_on(&w));
    assert(w.state == WD_TRIPPED);

    // 4. The trip latches. A controller that comes back to life must not be able
    //    to re-energise the motors by itself.
    for (int i = 0; i < 100; i++) {
        wd_heartbeat(&w);
        ticks(&w, HB_PERIOD_MS);
    }
    assert(!wd_relay_on(&w));

    // 5. A watchdog reset (firmware hang) boots straight into the latched state.
    wd_init(&w, 1);
    assert(w.state == WD_TRIPPED);
    arm(&w);
    assert(!wd_relay_on(&w));

    // 6. Noise cannot hold the relay closed: an implausibly early edge trips.
    wd_init(&w, 0);
    arm(&w);
    assert(wd_relay_on(&w));
    wd_heartbeat(&w);                  // restart the gap from zero
    ticks(&w, HB_MIN_GAP_MS - 1u);
    wd_heartbeat(&w);                  // 19 ms later: too early to be a heartbeat
    assert(!wd_relay_on(&w));

    // 7. Noise cannot arm it either: a 1 kHz burst never reaches three good
    //    edges, because every early edge clears the count.
    wd_init(&w, 0);
    for (unsigned t = 0; t < 1000u; t++) {
        wd_heartbeat(&w);
        ticks(&w, 1u);
        assert(!wd_relay_on(&w));
    }

    // 8. A heartbeat exactly at the minimum gap is still accepted, so jitter on
    //    the 50 ms heartbeat does not cause nuisance trips.
    wd_init(&w, 0);
    for (int i = 0; i < 10; i++) {
        wd_heartbeat(&w);
        ticks(&w, HB_MIN_GAP_MS);
    }
    assert(wd_relay_on(&w));

    printf("safety_watchdog core: all assertions passed\n");
    return 0;
}
