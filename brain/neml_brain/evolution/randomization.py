# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 11.4 domain randomisation (T-037) and the SPEC 11.2 seed discipline.

Every stream of randomness in the evolution loop is derived here from the run
seed. Nothing reads the wall clock, so the same seed replays exactly.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Mapping
from typing import Any

# SPEC 11.4 -- +/-15% on every randomised parameter.
RANDOMIZATION_RANGE = 0.15

# SPEC 11.4 nominals. link_masses come from CAD and motor_torque_constant from the
# actuator datasheet, so both are supplied per genome rather than hardcoded.
NOMINALS: dict[str, float] = {
    "surface_friction": 0.7,
    "imu_noise_sigma_rads": 0.01,
    "encoder_noise_sigma_rad": 0.002,
    "control_latency_s": 0.008,
}


def derive_rng(seed: int, label: str = "") -> random.Random:
    """SPEC 11.2 rule 1: an independent but reproducible stream per subsystem."""
    digest = hashlib.blake2b(f"{seed}:{label}".encode(), digest_size=8).digest()
    # Simulation, not cryptography. ruff reads the noqa, bandit only reads the nosec.
    return random.Random(int.from_bytes(digest, "big"))  # noqa: S311  # nosec B311


def _jitter(rng: random.Random, nominal: float, span: float) -> float:
    return nominal * (1.0 + rng.uniform(-span, span))


def randomize(
    seed: int,
    link_masses_kg: Mapping[str, float],
    motor_torque_constant: float,
    nominals: Mapping[str, float] | None = None,
    span: float = RANDOMIZATION_RANGE,
) -> dict[str, Any]:
    """Sample the six SPEC 11.4 parameters for one sim run.

    The returned dict is the record required by T-037: it goes into
    sim_runs.metrics so the exact conditions of the run can be replayed.
    """
    base = dict(NOMINALS if nominals is None else nominals)
    rng = derive_rng(seed, "domain_randomization")
    return {
        "seed": seed,
        "span": span,
        "surface_friction": _jitter(rng, base["surface_friction"], span),
        "link_masses_kg": {
            name: _jitter(rng, mass, span) for name, mass in sorted(link_masses_kg.items())
        },
        "imu_noise_sigma_rads": _jitter(rng, base["imu_noise_sigma_rads"], span),
        "encoder_noise_sigma_rad": _jitter(rng, base["encoder_noise_sigma_rad"], span),
        "control_latency_s": _jitter(rng, base["control_latency_s"], span),
        "motor_torque_constant": _jitter(rng, motor_torque_constant, span),
    }
