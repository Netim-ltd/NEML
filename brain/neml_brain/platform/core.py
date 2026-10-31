# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Command hierarchy and versioned events; transport and storage are adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum
from typing import Any


class Rank(IntEnum):
    STRATEGY = 0
    DOMAIN = 1
    TEAM = 2
    ROBOT = 3


@dataclass(frozen=True)
class Scope:
    tenant_id: str
    domain_id: str

    def __post_init__(self) -> None:
        if not self.tenant_id or not self.domain_id:
            raise ValueError("tenant and domain are required")


@dataclass(frozen=True)
class Unit:
    id: str
    scope: Scope
    rank: Rank
    parent_id: str | None
    safe_default: str = "hold_position"


@dataclass(frozen=True)
class Command:
    id: str
    scope: Scope
    source_id: str
    target_id: str
    parent_epoch: int
    expires_at: datetime
    action: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Event:
    id: str
    scope: Scope
    kind: str
    subject_id: str
    occurred_at: datetime
    payload: dict[str, Any]
    schema_version: int = 1


class Hierarchy:
    """Fail-closed command routing with epoch and deadline checks.

    The caller must persist accepted command IDs and events in one transaction.
    This class keeps no durable state and cannot serve as an actuator gate.
    """

    def __init__(self, units: list[Unit]) -> None:
        self.units = {unit.id: unit for unit in units}
        if len(self.units) != len(units):
            raise ValueError("duplicate unit id")
        for unit in units:
            if unit.rank is Rank.STRATEGY:
                if unit.parent_id is not None:
                    raise ValueError("strategy cannot have a parent")
            elif unit.parent_id not in self.units:
                raise ValueError(f"missing parent: {unit.id}")
            if unit.parent_id is not None:
                parent = self.units[unit.parent_id]
                if parent.scope != unit.scope or parent.rank + 1 != unit.rank:
                    raise ValueError(f"invalid hierarchy edge: {unit.id}")

    def route(self, command: Command, *, epoch: int, now: datetime | None = None) -> Unit:
        source = self.units[command.source_id]
        target = self.units[command.target_id]
        if command.scope != source.scope or command.scope != target.scope:
            raise PermissionError("cross-scope command")
        if target.parent_id != source.id:
            raise PermissionError("command must follow a direct hierarchy edge")
        if command.parent_epoch != epoch:
            raise PermissionError("stale parent epoch")
        if command.expires_at <= (now or datetime.now(UTC)):
            raise PermissionError("expired command")
        return target

    def safe_action(self, unit_id: str, *, parent_online: bool) -> str | None:
        unit = self.units[unit_id]
        return None if parent_online or unit.rank is Rank.STRATEGY else unit.safe_default


class EventLedger:
    """In-memory adapter for contract tests and single-process demos."""

    def __init__(self) -> None:
        self._events: dict[str, Event] = {}

    def append(self, event: Event) -> bool:
        prior = self._events.get(event.id)
        if prior is not None:
            if prior != event:
                raise ValueError("event ID reused with different content")
            return False
        self._events[event.id] = event
        return True

    def read(self, scope: Scope) -> list[Event]:
        return [event for event in self._events.values() if event.scope == scope]
