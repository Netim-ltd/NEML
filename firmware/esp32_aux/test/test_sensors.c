// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Host test for the esp32_aux sensor arithmetic. Scaling bugs here are silent:
// the telemetry still looks plausible, it is just wrong, and the SPEC 13.3
// limits are then checked against a number that means nothing.
//
//   cmake -B build-test -DHOST_TESTS=ON && cmake --build build-test && ctest --test-dir build-test

#include <assert.h>
#include <math.h>
#include <stdio.h>

#include "sensors.h"

static int close_to(float a, float b, float eps)
{
    return fabsf(a - b) <= eps;
}

static void test_limits_are_the_spec(void)
{
    assert(close_to(AUX_MAX_CURRENT_A, 20.0f, 1e-6f));   // SPEC 13.3 body_current_a_max
    assert(close_to(AUX_MAX_TEMP_C, 70.0f, 1e-6f));      // SPEC 13.3 body_temp_c_max
}

static void test_ina226_scaling(void)
{
    // 20 A full scale over a 2 mOhm shunt: CAL = 0.00512 / (LSB * R).
    const float lsb = ina226_current_lsb_a(INA226_MAX_CURRENT_A);
    assert(close_to(lsb, 20.0f / 32768.0f, 1e-9f));
    assert(ina226_calibration(0.002f, 20.0f) == 4194u);

    // 4S LiPo at full charge, 1.25 mV per bit.
    assert(close_to(ina226_bus_volts(13440u), 16.8f, 1e-3f));
    assert(close_to(ina226_bus_volts(0u), 0.0f, 1e-6f));

    // Current is signed: charging must not read as a 40 A discharge.
    assert(close_to(ina226_amps(16384, lsb), 10.0f, 1e-3f));
    assert(close_to(ina226_amps(-16384, lsb), -10.0f, 1e-3f));

    // An absurd shunt must not produce a calibration that wraps.
    assert(ina226_calibration(0.000001f, 20.0f) == 65535u);
}

static void test_ntc(void)
{
    // Divider at half the reference means the NTC equals the series resistor.
    const float r = ntc_resistance(NTC_VREF_V / 2.0f, NTC_VREF_V, NTC_SERIES_OHM);
    assert(close_to(r, NTC_SERIES_OHM, 1.0f));

    // At R0 the beta model returns T0 exactly.
    assert(close_to(ntc_celsius(NTC_R0_OHM, NTC_R0_OHM, NTC_T0_C, NTC_BETA_K),
                    NTC_T0_C + NTC_OFFSET_C, 1e-3f));

    // Monotonic and the right way round: less resistance means hotter.
    const float hot  = ntc_celsius(NTC_R0_OHM / 4.0f, NTC_R0_OHM, NTC_T0_C, NTC_BETA_K);
    const float cold = ntc_celsius(NTC_R0_OHM * 4.0f, NTC_R0_OHM, NTC_T0_C, NTC_BETA_K);
    assert(hot > NTC_T0_C);
    assert(cold < NTC_T0_C);

    // Open and shorted sensors report NaN, never a believable temperature.
    assert(ntc_resistance(0.0f, NTC_VREF_V, NTC_SERIES_OHM) < 0.0f);
    assert(ntc_resistance(NTC_VREF_V, NTC_VREF_V, NTC_SERIES_OHM) < 0.0f);
    assert(isnan(ntc_celsius(-1.0f, NTC_R0_OHM, NTC_T0_C, NTC_BETA_K)));
}

static void test_lipo_soc(void)
{
    // SPEC 13.3: 4 cells. Full, empty and the two ends of the curve.
    assert(close_to(lipo_soc(4.20f * LIPO_CELLS), 1.0f, 1e-6f));
    assert(close_to(lipo_soc(3.30f * LIPO_CELLS), 0.0f, 1e-6f));
    assert(close_to(lipo_soc(4.35f * LIPO_CELLS), 1.0f, 1e-6f));   // over the curve
    assert(close_to(lipo_soc(2.00f * LIPO_CELLS), 0.0f, 1e-6f));   // under it

    // Monotonic, and never outside 0..1.
    float previous = -1.0f;
    for (float cell = 3.0f; cell <= 4.4f; cell += 0.01f) {
        const float soc = lipo_soc(cell * LIPO_CELLS);
        assert(soc >= 0.0f && soc <= 1.0f);
        assert(soc >= previous);
        previous = soc;
    }

    // A known interpolation point: halfway between 3.80 V (0.50) and 3.90 V (0.70).
    assert(close_to(lipo_soc(3.85f * LIPO_CELLS), 0.60f, 1e-3f));

    // A broken voltage reading must not come out as a full battery.
    assert(isnan(lipo_soc(NAN)));
}

static void test_limit_checks(void)
{
    const float ok[3]        = {25.0f, 30.0f, 40.0f};
    const float hot[3]       = {25.0f, 71.0f, 40.0f};
    const float broken[3]    = {25.0f, NAN, 40.0f};

    assert(aux_check_limits(5.0f, ok, 3) == 0u);
    assert(aux_check_limits(25.0f, ok, 3) == AUX_FAULT_OVER_CURRENT);
    assert(aux_check_limits(-25.0f, ok, 3) == AUX_FAULT_OVER_CURRENT);   // charging too hard
    assert(aux_check_limits(5.0f, hot, 3) == AUX_FAULT_OVER_TEMP);
    assert(aux_check_limits(5.0f, broken, 3) == AUX_FAULT_SENSOR);

    // Exactly at the limit is still legal; one step past it is not.
    assert(aux_check_limits(AUX_MAX_CURRENT_A, ok, 3) == 0u);
    assert(aux_check_limits(AUX_MAX_CURRENT_A + 0.01f, ok, 3) == AUX_FAULT_OVER_CURRENT);
}

int main(void)
{
    test_limits_are_the_spec();
    test_ina226_scaling();
    test_ntc();
    test_lipo_soc();
    test_limit_checks();
    printf("esp32_aux sensors: all assertions passed\n");
    return 0;
}
