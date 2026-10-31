// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// NEML L0 safety watchdog - ATmega328P, bare metal avr-libc, no Arduino
// framework, no dynamic allocation. NEML_SPEC.md 5.1 and 16/T-071.
//
// ===========================================================================
// FAIL-SAFE WIRING - THIS IS THE WHOLE DESIGN. READ IT BEFORE CHANGING A LINE.
// ===========================================================================
// The motor relay is ENERGISED TO ALLOW MOTION.
//
//     coil energised (PB0 high) -> NO contact closed -> motor bus live
//     coil de-energised         -> contact open      -> motor bus dead
//
// Everything that can go wrong therefore stops the robot by doing nothing:
//
//   * MCU unpowered, held in reset or physically dead -> PB0 is high-Z and the
//     10k gate pull-down holds the relay FET off -> motor bus dead.
//   * Firmware hang -> the hardware watchdog (30 ms) resets the MCU -> PB0 goes
//     high-Z -> motor bus dead; WDRF then latches the fault on the way back up,
//     so a hung controller cannot re-energise the robot by rebooting.
//   * Heartbeat lost for 150 ms -> the 1 kHz tick drives PB0 low -> dead.
//   * Heartbeat cable cut -> the external pull-down holds the input low, no
//     edges arrive -> 150 ms timeout -> dead.
//   * E-stop pressed -> the NC mushroom button sits in series with the coil
//     supply, so the relay drops with no firmware involved at all (SPEC 5.1).
//   * Watchdog board loses power -> coil unpowered -> dead.
//
// No code path energises the relay other than three consecutive plausible
// heartbeats. Inverting the relay logic (energise to stop) breaks every line
// above. Do not "simplify" it.
//
// This MCU runs nothing else: no network, no bootloader, no brain link. SPEC 5.4
// puts safety.* out of reach of every agent and firmware.flash is a human CLI
// action only - see README.md.
// ===========================================================================
//
// Pinout (ATmega328P, 16 MHz crystal, 5 V):
//   PD2 / INT0  in   heartbeat from stm32_motion (PA5). 10k pull-down to GND
//                    plus a 1k + 10nF RC glitch filter at the pin.
//   PB0         out  relay FET gate, 10k pull-down to GND. HIGH = motion allowed.
//   PB1         out  status to the Pi 5 (neml_safety watchdog monitor, T-074).
//                    HIGH = armed. Driven from the same ISR as PB0.

#include <avr/interrupt.h>
#include <avr/io.h>
#include <avr/wdt.h>
#include <stdint.h>

#include "watchdog_core.h"

#define PB_RELAY       PB0
#define PB_STATUS      PB1
#define PD_HEARTBEAT   PD2

// Timer1 CTC at prescaler 64 must land exactly on 1 kHz, or the 150 ms in
// SPEC 5.1 is not 150 ms.
_Static_assert(F_CPU % (64UL * 1000UL) == 0UL, "1 ms tick is not exact at this F_CPU");
_Static_assert((F_CPU / 64UL / 1000UL - 1UL) <= 0xFFFFUL, "OCR1A overflow");

// Only the two ISRs touch g_wd. INT0 and TIMER1 cannot nest (avr-gcc clears the
// global interrupt enable on ISR entry), so no atomic guard is needed.
static wd_t g_wd;

// ISR -> main loop: "the 1 kHz tick is alive".
static volatile uint8_t g_tick;

#ifdef WDT_HANG_TEST
#pragma message("WDT_HANG_TEST build: T-071 step 4 firmware. Never leave it on the robot.")
static volatile uint16_t g_test_ms;
#endif

// Survives .init4, which clears .bss.
uint8_t g_mcusr __attribute__((section(".noinit")));

// MCUSR has to be read and the watchdog disabled before main(): after a watchdog
// reset the WDT is still running with its shortest timeout and would reset us
// forever. .init3 runs after the stack is set up and before .bss is cleared.
void wd_early_init(void) __attribute__((naked, used, section(".init3")));
void wd_early_init(void)
{
    g_mcusr = MCUSR;
    MCUSR = 0;
    wdt_disable();
}

ISR(INT0_vect)
{
    wd_heartbeat(&g_wd);
}

// The trip lives in the ISR, not in the main loop: detection latency is then one
// tick (<= 1 ms) plus the relay drop-out time, which is exactly what T-071
// measures on the scope.
ISR(TIMER1_COMPA_vect)
{
    wd_tick_1ms(&g_wd);

    if (wd_relay_on(&g_wd)) {
        PORTB |= (uint8_t)(_BV(PB_RELAY) | _BV(PB_STATUS));
    } else {
        PORTB &= (uint8_t)~(_BV(PB_RELAY) | _BV(PB_STATUS));
    }

    g_tick = 1u;
#ifdef WDT_HANG_TEST
    g_test_ms++;
#endif
}

int main(void)
{
    // Drive low before switching to output: no glitch, motion inhibited from the
    // first instruction.
    PORTB &= (uint8_t)~(_BV(PB_RELAY) | _BV(PB_STATUS));
    DDRB  |= (uint8_t)(_BV(PB_RELAY) | _BV(PB_STATUS));
    DDRD  &= (uint8_t)~_BV(PD_HEARTBEAT);   // input; external pull-down, no internal one

    wd_init(&g_wd, (uint8_t)(g_mcusr & _BV(WDRF)));

    // INT0 on any logical change. A line stuck high is as dead as one stuck low,
    // so we count edges, never levels.
    EICRA = _BV(ISC00);
    EIMSK = _BV(INT0);

    // Timer1, CTC, prescaler 64 -> 1 kHz.
    TCCR1A = 0;
    TCCR1B = _BV(WGM12) | _BV(CS11) | _BV(CS10);
    OCR1A  = (uint16_t)(F_CPU / 64UL / 1000UL - 1UL);
    TIMSK1 = _BV(OCIE1A);

    // Second layer: if this loop stops running, the MCU resets and the relay
    // drops. 30 ms is well inside the 150 ms budget.
    wdt_enable(WDTO_30MS);
    sei();

    for (;;) {
        // The hardware watchdog is fed only while the 1 kHz tick is alive. If the
        // timer ever dies the relay would otherwise freeze in its last state, so
        // we stop feeding and let the reset open it.
        if (g_tick) {
            g_tick = 0u;
            wdt_reset();
        }
#ifdef WDT_HANG_TEST
        if (g_test_ms > 2000u) {
            cli();
            for (;;) { }   // T-071 step 4: hang on purpose and scope the WDT path
        }
#endif
    }
}
