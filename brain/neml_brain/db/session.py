# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Async engine/session wiring for neml-brain (SPEC 8.1). The URL comes from NEML_DB_URL
# (SPEC 17.3), e.g. postgresql+asyncpg://neml:...@localhost:5432/neml_local.

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from functools import lru_cache

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """Process-wide async engine. Lazy so importing this module never needs a database."""
    return create_async_engine(os.environ["NEML_DB_URL"], pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: `session: AsyncSession = Depends(get_session)`."""
    async with get_sessionmaker()() as session:
        yield session


async def db_healthy() -> bool:
    """Component probe for GET /health (SPEC 8.3)."""
    try:
        async with get_engine().connect() as conn:
            await conn.execute(sa.text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - /health reports down, it never raises
        return False
