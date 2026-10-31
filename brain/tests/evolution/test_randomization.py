# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 11.4 domain randomisation (T-037): seeded, bounded, recorded."""

from __future__ import annotations

import pytest

from neml_brain.evolution.randomization import (
    NOMINALS,
    RANDOMIZATION_RANGE,
    derive_rng,
    randomize,
)

LINKS = {"leg_fl": 0.180, "leg_fr": 0.180, "body": 1.900}
TORQUE_CONSTANT = 0.0185


def _sample(seed: int):
    return randomize(seed, link_masses_kg=LINKS, motor_torque_constant=TORQUE_CONSTANT)


def test_the_six_spec_parameters_are_randomised():
    sample = _sample(1)
    assert set(sample) == {
        "seed",
        "span",
        "surface_friction",
        "link_masses_kg",
        "imu_noise_sigma_rads",
        "encoder_noise_sigma_rad",
        "control_latency_s",
        "motor_torque_constant",
    }
    assert NOMINALS == {
        "surface_friction": 0.7,
        "imu_noise_sigma_rads": 0.01,
        "encoder_noise_sigma_rad": 0.002,
        "control_latency_s": 0.008,
    }
    assert RANDOMIZATION_RANGE == 0.15


def test_the_same_seed_replays_exactly():
    assert _sample(4242) == _sample(4242)
    assert _sample(4242) != _sample(4243)


def test_the_run_record_carries_the_seed():
    sample = _sample(99)
    assert sample["seed"] == 99
    assert sample["span"] == RANDOMIZATION_RANGE


@pytest.mark.parametrize("seed", range(25))
def test_every_parameter_stays_within_fifteen_percent(seed):
    sample = _sample(seed)
    span = RANDOMIZATION_RANGE
    for name, nominal in NOMINALS.items():
        assert nominal * (1 - span) <= sample[name] <= nominal * (1 + span)
    assert (
        TORQUE_CONSTANT * (1 - span)
        <= sample["motor_torque_constant"]
        <= TORQUE_CONSTANT * (1 + span)
    )
    for link, mass in LINKS.items():
        assert mass * (1 - span) <= sample["link_masses_kg"][link] <= mass * (1 + span)


def test_link_masses_are_randomised_independently():
    sample = _sample(7)
    assert sample["link_masses_kg"]["leg_fl"] != sample["link_masses_kg"]["leg_fr"]


def test_derive_rng_gives_independent_but_reproducible_streams():
    assert derive_rng(1, "a").random() == derive_rng(1, "a").random()
    assert derive_rng(1, "a").random() != derive_rng(1, "b").random()
    assert derive_rng(1, "a").random() != derive_rng(2, "a").random()
