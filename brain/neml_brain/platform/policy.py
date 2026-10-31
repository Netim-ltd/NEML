# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Small, deterministic per-type contextual policy suitable for an edge CPU.

This bounded linear policy is intentionally auditable. It never chooses an
actuator value directly; it chooses among plugin-approved symbolic actions.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PolicySample:
    features: tuple[float, ...]
    action: str
    reward: float


@dataclass(frozen=True)
class LinearPolicy:
    robot_type: str
    actions: tuple[str, ...]
    feature_count: int
    weights: dict[str, tuple[float, ...]]

    @classmethod
    def empty(cls, robot_type: str, actions: tuple[str, ...], feature_count: int) -> LinearPolicy:
        if not robot_type or not actions or len(set(actions)) != len(actions):
            raise ValueError("invalid policy identity/actions")
        if feature_count < 1 or feature_count > 64:
            raise ValueError("feature count must be 1..64")
        return cls(robot_type, actions, feature_count, {a: (0.0,) * feature_count for a in actions})

    def choose(self, features: tuple[float, ...]) -> str:
        self._check_features(features)
        return max(
            self.actions,
            key=lambda a: sum(x * w for x, w in zip(features, self.weights[a], strict=True)),
        )

    def _check_features(self, features: tuple[float, ...]) -> None:
        if len(features) != self.feature_count or any(
            not math.isfinite(x) or abs(x) > 1 for x in features
        ):
            raise ValueError("features must be normalized to [-1,1]")

    def update(self, samples: list[PolicySample], *, learning_rate: float = 0.05) -> LinearPolicy:
        if not 0 < learning_rate <= 0.1:
            raise ValueError("learning rate must be in (0,0.1]")
        weights = {action: list(values) for action, values in self.weights.items()}
        for sample in samples:
            self._check_features(sample.features)
            if sample.action not in weights or not -1 <= sample.reward <= 1:
                raise ValueError("invalid policy sample")
            row = weights[sample.action]
            prediction = sum(x * w for x, w in zip(sample.features, row, strict=True))
            error = max(-1.0, min(1.0, sample.reward - prediction))
            weights[sample.action] = [
                max(-4.0, min(4.0, w + learning_rate * error * x))
                for w, x in zip(row, sample.features, strict=True)
            ]
        return LinearPolicy(
            self.robot_type,
            self.actions,
            self.feature_count,
            {action: tuple(values) for action, values in weights.items()},
        )

    def to_bytes(self) -> bytes:
        body: dict[str, Any] = {
            "format": "neml-linear-policy-v1",
            "robot_type": self.robot_type,
            "actions": self.actions,
            "feature_count": self.feature_count,
            "weights": self.weights,
        }
        return json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()

    @classmethod
    def from_bytes(cls, payload: bytes) -> LinearPolicy:
        data = json.loads(payload)
        if data.get("format") != "neml-linear-policy-v1":
            raise ValueError("unsupported policy format")
        actions = tuple(data["actions"])
        count = int(data["feature_count"])
        base = cls.empty(str(data["robot_type"]), actions, count)
        weights = {a: tuple(float(x) for x in data["weights"][a]) for a in actions}
        if any(
            len(row) != count or any(not math.isfinite(value) or abs(value) > 4 for value in row)
            for row in weights.values()
        ):
            raise ValueError("invalid policy weights")
        return cls(base.robot_type, actions, count, weights)
