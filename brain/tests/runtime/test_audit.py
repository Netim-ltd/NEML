# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 5.4 audit_log writer."""

from __future__ import annotations

from typing import Any

from neml_brain.runtime.audit import AuditLog, params_hash


async def test_writes_every_spec_column(audit: AuditLog, rows: list[dict[str, Any]]) -> None:
    await audit.write(
        actor="agent:mechanical",
        action="cad.export",
        target="artifact:42",
        params={"step": True},
        outcome="allowed",
        duration_ms=17,
        approval_id="0f7c7b1e-0000-0000-0000-000000000000",
    )
    row = rows[0]
    assert set(row) == {
        "actor",
        "action",
        "target",
        "params_hash",
        "outcome",
        "duration_ms",
        "approval_id",
    }
    assert row["params_hash"] == params_hash({"step": True})
    assert row["duration_ms"] == 17


async def test_params_are_hashed_not_stored(audit: AuditLog, rows: list[dict[str, Any]]) -> None:
    await audit.write(actor="user:mg", action="printer.start", params={"api_key": "s3cret"})
    assert "s3cret" not in str(rows[0])
    assert len(rows[0]["params_hash"]) == 64


async def test_no_params_means_no_hash(audit: AuditLog, rows: list[dict[str, Any]]) -> None:
    await audit.write(actor="gate", action="level0", outcome="auto_approved")
    assert rows[0]["params_hash"] is None


def test_hash_is_stable_and_key_order_independent() -> None:
    assert params_hash({"a": 1, "b": 2}) == params_hash({"b": 2, "a": 1})
    assert params_hash({"a": 1}) != params_hash({"a": 2})
