# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Non-finite sensor and model numbers must fail closed."""

import pytest

from neml_brain.platform.policy import LinearPolicy
from neml_brain.platform.robots import HomeRobot


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_safety_envelope_rejects_nonfinite_actuation(value: float) -> None:
    envelope = HomeRobot().envelope
    with pytest.raises(PermissionError):
        envelope.constrain(speed_mps=value, force_n=0.0, zone="home_clear", estop=False)
    with pytest.raises(PermissionError):
        envelope.constrain(speed_mps=0.0, force_n=value, zone="home_clear", estop=False)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_policy_rejects_nonfinite_features_and_weights(value: float) -> None:
    policy = LinearPolicy.empty("home_v1", ("stop", "navigate"), 1)
    with pytest.raises(ValueError):
        policy.choose((value,))
    raw = policy.to_bytes().decode().replace('"stop":[0.0]', f'"stop":[{value}]')
    with pytest.raises((ValueError, TypeError)):
        LinearPolicy.from_bytes(raw.encode())
