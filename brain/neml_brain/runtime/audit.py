# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 5.4 audit log: agent, tool, params hash, outcome, duration, approval reference.

Parameters are hashed, never stored. A secret that leaks into a tool parameter
must not become a two-year retained row (SPEC 18.3).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from sqlalchemy import text

_INSERT = text(
    "INSERT INTO audit_log"
    " (actor, action, target, params_hash, outcome, duration_ms, approval_id)"
    " VALUES (:actor, :action, :target, :params_hash, :outcome, :duration_ms,"
    " CAST(:approval_id AS uuid))"
)


class Session(Protocol):
    """The slice of sqlalchemy.ext.asyncio.AsyncSession this package uses."""

    async def execute(self, statement: Any, parameters: Any = None) -> Any: ...

    async def commit(self) -> None: ...


SessionFactory = Callable[[], AbstractAsyncContextManager[Session]]


def params_hash(params: object) -> str:
    """SHA-256 over the canonical JSON form. Raw values never leave this function."""
    blob = json.dumps(params, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


class AuditLog:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def write(
        self,
        *,
        actor: str,
        action: str,
        target: str | None = None,
        params: object | None = None,
        outcome: str | None = None,
        duration_ms: int | None = None,
        approval_id: str | None = None,
    ) -> None:
        async with self._session_factory() as session:
            await session.execute(
                _INSERT,
                {
                    "actor": actor,
                    "action": action,
                    "target": target,
                    "params_hash": None if params is None else params_hash(params),
                    "outcome": outcome,
                    "duration_ms": duration_ms,
                    "approval_id": approval_id,
                },
            )
            await session.commit()
