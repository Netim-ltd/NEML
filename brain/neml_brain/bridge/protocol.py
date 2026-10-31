# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bridge wire contract (SPEC 9.5) - lab <-> cloud, both directions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import IntEnum
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

PROTOCOL_VERSION: Literal[1] = 1

# SPEC 9.5: lab -> server
LabMessageType = Literal["telemetry", "state", "event", "command_ack", "approval_request", "log"]
# SPEC 9.5: server -> lab
ServerMessageType = Literal["command", "approval_decision", "ping"]
MessageType = Literal[
    "telemetry",
    "state",
    "event",
    "command_ack",
    "approval_request",
    "log",
    "command",
    "approval_decision",
    "ping",
]

LAB_TYPES: frozenset[str] = frozenset(get_args(LabMessageType))
SERVER_TYPES: frozenset[str] = frozenset(get_args(ServerMessageType))


class Priority(IntEnum):
    """Outbox drop class (SPEC 9.5).

    "dolunca en eski telemetri dusurulur (event ve ack asla dusmez)" - when the
    queue is full only telemetry is evicted. Everything else is durable: the
    asymmetry is a type, not a convention.
    """

    DROPPABLE = 0
    DURABLE = 1


def priority_of(message_type: str) -> Priority:
    return Priority.DROPPABLE if message_type == "telemetry" else Priority.DURABLE


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Envelope(_Strict):
    """SPEC 9.5 message envelope. Every message on the wire is one of these."""

    v: Literal[1] = PROTOCOL_VERSION
    seq: int = Field(ge=0)
    ts: datetime
    type: MessageType
    idempotency_key: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)

    @property
    def priority(self) -> Priority:
        return priority_of(self.type)


class BrainStatusPayload(_Strict):
    """SPEC 9.5 heartbeat verdict: BrainStatus{online:false} on 45 s of silence."""

    node_id: str
    online: bool


class CommandPayload(_Strict):
    """server -> lab `command`, pulled from the cloud command queue (SPEC 7)."""

    command_id: str
    kind: str
    args: dict[str, Any] = Field(default_factory=dict)


class ApprovalDecisionPayload(_Strict):
    """server -> lab `approval_decision` (SPEC 5.2)."""

    approval_id: str
    decision: Literal["approved", "rejected", "expired"]
    decided_by: str
    note: str | None = None


class CommandAckPayload(_Strict):
    """lab -> server `command_ack`; mirrors commands.state (SPEC 7)."""

    command_id: str
    state: Literal["applied", "failed", "rejected"]
    result: dict[str, Any] = Field(default_factory=dict)


def new_envelope(
    seq: int,
    message_type: MessageType,
    payload: dict[str, Any] | None = None,
    *,
    idempotency_key: str | None = None,
) -> Envelope:
    return Envelope(
        seq=seq,
        ts=datetime.now(UTC),
        type=message_type,
        idempotency_key=idempotency_key or uuid.uuid4().hex,
        payload=payload or {},
    )
