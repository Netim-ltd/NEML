# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 9.5 envelope + drop-class contract."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from neml_brain.bridge.protocol import (
    LAB_TYPES,
    SERVER_TYPES,
    ApprovalDecisionPayload,
    CommandPayload,
    Envelope,
    Priority,
    new_envelope,
    priority_of,
)


def test_direction_sets_match_spec():
    assert LAB_TYPES == {"telemetry", "state", "event", "command_ack", "approval_request", "log"}
    assert SERVER_TYPES == {"command", "approval_decision", "ping"}
    assert not LAB_TYPES & SERVER_TYPES


@pytest.mark.parametrize(
    ("message_type", "expected"),
    [
        ("telemetry", Priority.DROPPABLE),
        ("event", Priority.DURABLE),
        ("command_ack", Priority.DURABLE),
        ("state", Priority.DURABLE),
        ("approval_request", Priority.DURABLE),
        ("log", Priority.DURABLE),
    ],
)
def test_only_telemetry_is_droppable(message_type, expected):
    assert priority_of(message_type) is expected


def test_envelope_round_trip():
    env = new_envelope(7, "event", {"kind": "estop"})
    wire = env.model_dump_json()
    back = Envelope.model_validate_json(wire)
    assert back == env
    assert back.v == 1
    assert back.priority is Priority.DURABLE


def test_envelope_is_strict():
    with pytest.raises(ValidationError):  # unknown field
        Envelope(
            seq=1,
            ts=datetime.now(UTC),
            type="event",
            idempotency_key="k",
            payload={},
            extra_field=1,
        )
    with pytest.raises(ValidationError):  # unknown type
        Envelope(seq=1, ts=datetime.now(UTC), type="nope", idempotency_key="k")
    with pytest.raises(ValidationError):  # empty idempotency key
        Envelope(seq=1, ts=datetime.now(UTC), type="event", idempotency_key="")
    with pytest.raises(ValidationError):  # protocol version is pinned at 1
        Envelope.model_validate_json(
            '{"v":2,"seq":1,"ts":"2026-09-15T10:22:31.442Z","type":"ping",'
            '"idempotency_key":"k","payload":{}}'
        )


def test_server_payloads_are_strict():
    cmd = CommandPayload(command_id="c1", kind="run_task", args={"task_id": "t1"})
    assert cmd.kind == "run_task"
    decision = ApprovalDecisionPayload(approval_id="a1", decision="approved", decided_by="user:mg")
    assert decision.note is None
    with pytest.raises(ValidationError):
        ApprovalDecisionPayload(approval_id="a1", decision="maybe", decided_by="user:mg")
