# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Robot type plugins, model metadata, and immutable actuator limits."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime
from importlib.metadata import entry_points
from typing import Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from neml_brain.platform.core import Scope


@dataclass(frozen=True)
class SafetyEnvelope:
    max_speed_mps: float
    max_force_n: float
    allowed_zones: frozenset[str]

    def constrain(self, *, speed_mps: float, force_n: float, zone: str, estop: bool) -> None:
        if estop or zone not in self.allowed_zones:
            raise PermissionError("estop or forbidden zone")
        if not math.isfinite(speed_mps) or not math.isfinite(force_n):
            raise PermissionError("non-finite actuator request")
        if abs(speed_mps) > self.max_speed_mps or abs(force_n) > self.max_force_n:
            raise PermissionError("actuator limit exceeded")


class RobotTypePlugin(Protocol):
    type_id: str
    capabilities: frozenset[str]
    envelope: SafetyEnvelope
    safe_default: str

    def supports(self, capabilities: frozenset[str]) -> bool: ...


@dataclass(frozen=True)
class HomeRobot:
    type_id: str = "home_v1"
    capabilities: frozenset[str] = frozenset({"navigate_indoor", "inspect_room"})
    envelope: SafetyEnvelope = SafetyEnvelope(0.25, 5.0, frozenset({"home_clear"}))
    safe_default: str = "stop_and_hold"

    def supports(self, capabilities: frozenset[str]) -> bool:
        return capabilities <= self.capabilities


@dataclass(frozen=True)
class FieldRobot:
    type_id: str = "field_v1"
    capabilities: frozenset[str] = frozenset({"navigate_field", "inspect_crop"})
    envelope: SafetyEnvelope = SafetyEnvelope(0.5, 12.0, frozenset({"field_marked"}))
    safe_default: str = "stop_and_hold"

    def supports(self, capabilities: frozenset[str]) -> bool:
        return capabilities <= self.capabilities


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, RobotTypePlugin] = {}

    def register(self, plugin: RobotTypePlugin) -> None:
        if plugin.type_id in self._plugins:
            raise ValueError("duplicate robot type")
        self._plugins[plugin.type_id] = plugin

    def capable(self, capabilities: frozenset[str]) -> list[RobotTypePlugin]:
        return [plugin for plugin in self._plugins.values() if plugin.supports(capabilities)]

    def load_installed(self) -> None:
        """Discover installed robot types without editing the platform core.

        Packaging and installation are operator-controlled; a tenant cannot
        upload executable Python as a plugin through an API request.
        """
        for point in entry_points(group="neml.robot_types"):
            factory = point.load()
            plugin: RobotTypePlugin = factory()
            self.register(plugin)


@dataclass(frozen=True)
class ModelCard:
    scope: Scope
    robot_type: str
    version: str
    artifact_sha256: str
    signature: str
    training_start: datetime
    training_end: datetime
    metrics: dict[str, float]
    rollback_version: str | None


class ModelRegistry:
    """Metadata boundary; callers keep model bytes in immutable artifact storage.

    The private seed belongs only on the lab. Edge devices receive the public
    key and never get signing material. Production key custody can move to KMS.
    """

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("Ed25519 private seed must be 32 bytes")
        self._private = Ed25519PrivateKey.from_private_bytes(key)
        self.public_key = self._private.public_key()
        self._cards: dict[tuple[Scope, str, str], ModelCard] = {}

    def public_key_bytes(self) -> bytes:
        return self.public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)

    def sign(self, scope: Scope, robot_type: str, version: str, artifact: bytes) -> str:
        digest = hashlib.sha256(artifact).hexdigest()
        data = f"{scope.tenant_id}:{scope.domain_id}:{robot_type}:{version}:{digest}"
        return self._private.sign(data.encode()).hex()

    def add(self, card: ModelCard, artifact: bytes) -> None:
        if card.training_end < card.training_start:
            raise ValueError("invalid training range")
        if hashlib.sha256(artifact).hexdigest() != card.artifact_sha256:
            raise ValueError("artifact digest mismatch")
        data = (
            f"{card.scope.tenant_id}:{card.scope.domain_id}:"
            f"{card.robot_type}:{card.version}:{card.artifact_sha256}"
        )
        try:
            self.public_key.verify(bytes.fromhex(card.signature), data.encode())
        except (InvalidSignature, ValueError) as exc:
            raise PermissionError("invalid model signature") from exc
        key = (card.scope, card.robot_type, card.version)
        if key in self._cards:
            raise ValueError("model version already registered")
        self._cards[key] = card

    def get(self, scope: Scope, robot_type: str, version: str) -> ModelCard:
        return self._cards[(scope, robot_type, version)]
