# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 5.2 / 5.5 deployment gates."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest

from neml_brain.safety.gates import (
    ApprovalDenied,
    ApprovalExpired,
    DeploymentGate,
    Level,
)

FAST = {"ttl": timedelta(seconds=2), "poll_interval_s": 0.01}


def gate(session_factory: Any, audit: Any, **kwargs: Any) -> DeploymentGate:
    return DeploymentGate(session_factory, audit, owners={"user:mg"}, **{**FAST, **kwargs})


async def decide_soon(db: Any, decision: str, decided_by: str = "user:mg") -> None:
    for _ in range(200):
        await asyncio.sleep(0.005)
        if db.approvals:
            db.decide(next(iter(db.approvals)), decision, decided_by)
            return
    raise AssertionError("no approval row was ever created")


async def test_level0_is_automatic_and_creates_no_row(
    session_factory: Any, audit: Any, db: Any
) -> None:
    approval = await gate(session_factory, audit).require_approval(Level.SIM, "task", "t-1", {})
    assert approval.id is None
    assert db.approvals == {}
    assert db.audit[-1]["outcome"] == "auto_approved"


@pytest.mark.parametrize("level", [Level.BENCH, Level.TETHERED, Level.FREE])
async def test_levels_1_to_3_block_until_approved(
    session_factory: Any, audit: Any, db: Any, level: Level
) -> None:
    task = asyncio.create_task(decide_soon(db, "approved", "user:operator"))
    approval = await gate(session_factory, audit).require_approval(level, "task", "t-2", {"a": 1})
    await task
    assert approval.id is not None
    assert approval.decided_by == "user:operator"
    assert db.audit[-1]["outcome"] == "approved"


async def test_rejection_raises(session_factory: Any, audit: Any, db: Any) -> None:
    task = asyncio.create_task(decide_soon(db, "rejected"))
    with pytest.raises(ApprovalDenied):
        await gate(session_factory, audit).require_approval(Level.BENCH, "task", "t-3", {})
    await task


async def test_expiry_auto_rejects(session_factory: Any, audit: Any, db: Any) -> None:
    g = gate(session_factory, audit, ttl=timedelta(milliseconds=30))
    with pytest.raises(ApprovalExpired):
        await g.require_approval(Level.TETHERED, "task", "t-4", {})
    row = next(iter(db.approvals.values()))
    assert row["decision"] == "expired"
    assert db.audit[-1]["outcome"] == "expired"


async def test_level4_rejects_a_non_owner_approval(
    session_factory: Any, audit: Any, db: Any
) -> None:
    task = asyncio.create_task(decide_soon(db, "approved", "user:operator"))
    with pytest.raises(ApprovalDenied, match="owner"):
        await gate(session_factory, audit).require_approval(
            Level.MANUFACTURE, "print", "p-1", {"grams": 20}
        )
    await task
    assert next(iter(db.approvals.values()))["decision"] == "rejected"
    assert db.audit[-1]["outcome"] == "denied:not_owner"


async def test_level4_accepts_the_owner(session_factory: Any, audit: Any, db: Any) -> None:
    task = asyncio.create_task(decide_soon(db, "approved", "user:mg"))
    approval = await gate(session_factory, audit).require_approval(
        Level.MANUFACTURE, "print", "p-2", {"grams": 20}
    )
    await task
    assert approval.decided_by == "user:mg"


async def test_unconfigured_lab_cannot_approve_level4(
    session_factory: Any, audit: Any, db: Any
) -> None:
    g = DeploymentGate(session_factory, audit, owners=(), **FAST)
    task = asyncio.create_task(decide_soon(db, "approved", "user:mg"))
    with pytest.raises(ApprovalDenied):
        await g.require_approval(Level.MANUFACTURE, "firmware", "f-1", {})
    await task


def test_there_is_no_bypass_parameter() -> None:
    import inspect

    params = set(inspect.signature(DeploymentGate.require_approval).parameters)
    assert params == {"self", "level", "subject_kind", "subject_id", "payload"}
