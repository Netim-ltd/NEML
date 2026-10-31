# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""model_settings rows (migration 0006). Plain SQL: the table is not a SPEC 7 table."""

from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from neml_brain.settings import catalog


class SettingsStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def model_ids(self) -> list[str]:
        """The lab pseudo-model plus every model a registered robot runs."""
        async with self._sessions() as session:
            rows = await session.execute(
                sa.text(
                    "SELECT DISTINCT g.name FROM robots r JOIN genomes g ON g.id = r.genome_id"
                    " ORDER BY g.name"
                )
            )
            return [catalog.LAB, *(r[0] for r in rows)]

    async def get(self, model_id: str) -> dict[str, Any]:
        async with self._sessions() as session:
            row = await session.execute(
                sa.text("SELECT values FROM model_settings WHERE model_id = :m"), {"m": model_id}
            )
            found = row.scalar_one_or_none()
        return dict(found) if found else {}

    async def put(self, model_id: str, values: dict[str, Any], actor: str) -> dict[str, Any]:
        """Merge `values` into the stored ones; a null removes a field."""
        merged = {**await self.get(model_id), **values}
        merged = {k: v for k, v in merged.items() if v is not None}
        async with self._sessions() as session:
            await session.execute(
                sa.text(
                    "INSERT INTO model_settings (model_id, values, updated_by)"
                    " VALUES (:m, CAST(:v AS jsonb), :a)"
                    " ON CONFLICT (model_id) DO UPDATE SET values = EXCLUDED.values,"
                    " updated_by = EXCLUDED.updated_by, updated_at = now()"
                ),
                {"m": model_id, "v": json.dumps(merged), "a": actor},
            )
            await session.commit()
        return merged
