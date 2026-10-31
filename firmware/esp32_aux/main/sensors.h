// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// NEML esp32_aux - sensor arithmetic (NEML_SPEC.md 13.3 sensors, limits).
//
// Pure functions, no ESP-IDF headers, so test/test_sensors.c runs them on a host
// compiler. main.c does the I2C and ADC transfers and calls in here to turn raw
// registers into physical units.

#ifndef NEML_AUX_SENSORS_H
#define NEML_AUX_SENSORS_H

#include <math.h>
#include <stdint.h>

#include "neml_limits.h"

// --- INA226 (SPEC 13.3 sensors: current, model ina226, count 2) -------------
// Datasheet LSBs. Bus voltage is unsigned, shunt voltage is signed.
#define INA226_BUS_LSB_V   0.00125f
#define INA226_SHUNT_LSB_V 0.0000025f

// Shunt on both channels. 2 mOhm gives 40 mV at 20 A, inside the +/- 81.92 mV
// range of the part. ponytail: calibrate per board - a 1 % shunt plus trace
// resistance is easily 3 % off, and the current limit in SPEC 13.3 is worth more
// than 3 %. Measure against a bench supply and adjust INA226_SHUNT_OHM.
#define INA226_SHUNT_OHM 0.002f

// Full scale current per channel. The body limit is 20 A (SPEC 13.3
// limits.body_current_a_max), so 20 A full scale keeps one LSB small and still
// reads the limit itself.
#define INA226_MAX_CURRENT_A ((float)LIMIT_BODY_CURRENT_MA / 1000.0f)

static inline float ina226_current_lsb_a(float max_current_a)
{
    return max_current_a / 32768.0f;
}

// Datasheet: CAL = 0.00512 / (current_LSB * R_shunt).
static inline uint16_t ina226_calibration(float shunt_ohm, float max_current_a)
{
    const float cal = 0.00512f / (ina226_current_lsb_a(max_current_a) * shunt_ohm);
    if (cal <= 0.0f) {
        return 0u;
    }
    if (cal >= 65535.0f) {
        return 65535u;
    }
    return (uint16_t)cal;
}

static inline float ina226_bus_volts(uint16_t raw)
{
    return (float)raw * INA226_BUS_LSB_V;
}

static inline float ina226_amps(int16_t raw, float current_lsb_a)
{
    return (float)raw * current_lsb_a;
}

// --- LiPo pack (SPEC 13.3 power.battery: lipo, 4S, 5200 mAh, 25C) -----------
#define LIPO_CELLS        4
#define LIPO_CAPACITY_AH  5.2f

// State of charge from pack voltage.
//
// ponytail: a resting-voltage lookup, not a coulomb counter. Under load it reads
// low by (pack internal resistance x current), which on this pack at 10 A is a
// few per cent, and the curve between 3.7 V and 3.9 V per cell is flat enough
// that a percentage there is a guess. It is good enough for "come home now",
// which is all the operator needs from it. Upgrade path: integrate the ina226
// current over time and use this only to seed and re-anchor the integral - worth
// doing if SPEC 13.3 performance.endurance_min ever has to come from telemetry.
static inline float lipo_soc(float pack_v)
{
    static const float curve_v[]   = {3.30f, 3.60f, 3.70f, 3.80f, 3.90f, 4.00f, 4.20f};
    static const float curve_soc[] = {0.00f, 0.10f, 0.25f, 0.50f, 0.70f, 0.87f, 1.00f};
    const int n = (int)(sizeof(curve_v) / sizeof(curve_v[0]));

    if (isnan(pack_v)) {
        return NAN;   // a dead sensor must never report a full battery
    }
    const float cell = pack_v / (float)LIPO_CELLS;
    if (cell <= curve_v[0]) {
        return 0.0f;
    }
    for (int i = 1; i < n; i++) {
        if (cell < curve_v[i]) {
            return curve_soc[i - 1] + (curve_soc[i] - curve_soc[i - 1]) *
                                          (cell - curve_v[i - 1]) /
                                          (curve_v[i] - curve_v[i - 1]);
        }
    }
    return 1.0f;
}

// --- NTC thermistor ---------------------------------------------------------
// SPEC 13.3 lists no temperature sensor model, so this is a 10k / B3950 NTC on
// ADC1 with a 10k series resistor to the 3.3 V rail. Every constant here is a
// calibration knob: the beta model is never the part, and the divider is never
// exactly 10k. Trim NTC_OFFSET_C against a reference thermometer at room
// temperature and again at 60 C.
#define NTC_R0_OHM     10000.0f
#define NTC_T0_C          25.0f
#define NTC_BETA_K      3950.0f
#define NTC_SERIES_OHM 10000.0f
#define NTC_VREF_V         3.3f
#define NTC_OFFSET_C       0.0f

// Low side NTC: Vadc = Vref * Rntc / (Rseries + Rntc).
static inline float ntc_resistance(float adc_v, float vref, float series_ohm)
{
    if (adc_v <= 0.0f || adc_v >= vref) {
        return -1.0f;   // open or shorted sensor
    }
    return series_ohm * adc_v / (vref - adc_v);
}

static inline float ntc_celsius(float r_ohm, float r0_ohm, float t0_c, float beta_k)
{
    if (r_ohm <= 0.0f) {
        return NAN;
    }
    const float t0 = t0_c + 273.15f;
    return 1.0f / (1.0f / t0 + logf(r_ohm / r0_ohm) / beta_k) - 273.15f + NTC_OFFSET_C;
}

// --- Limit checks (SPEC 13.3 limits) ---------------------------------------
#define AUX_FAULT_OVER_CURRENT 0x01u
#define AUX_FAULT_OVER_TEMP    0x02u
#define AUX_FAULT_SENSOR       0x04u   // open, shorted or unreadable sensor

#define AUX_MAX_CURRENT_A ((float)LIMIT_BODY_CURRENT_MA / 1000.0f)
#define AUX_MAX_TEMP_C    ((float)LIMIT_BODY_TEMP_MC / 1000.0f)

// Reporting only. This MCU cannot cut power and must not pretend to: L0 is the
// ATmega328P plus the hardware current comparator (SPEC 5.1), both independent
// of software.
static inline uint8_t aux_check_limits(float body_current_a, const float *temp_c, int n)
{
    uint8_t faults = 0u;

    if (body_current_a > AUX_MAX_CURRENT_A || body_current_a < -AUX_MAX_CURRENT_A) {
        faults |= AUX_FAULT_OVER_CURRENT;
    }
    for (int i = 0; i < n; i++) {
        if (isnan(temp_c[i])) {
            faults |= AUX_FAULT_SENSOR;
        } else if (temp_c[i] > AUX_MAX_TEMP_C) {
            faults |= AUX_FAULT_OVER_TEMP;
        }
    }
    return faults;
}

#endif  // NEML_AUX_SENSORS_H
