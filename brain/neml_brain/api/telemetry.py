# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""GET /v1/telemetry — time series query (SPEC 8.3, partitioned table SPEC 7)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query

from neml_brain.api import deps

router = APIRouter(prefix="/v1/telemetry", tags=["telemetry"])


@router.get("")
async def query_telemetry(
    repo: deps.Repo,
    robot_id: Annotated[str, Query(description="Indexed as (robot_id, metric, ts DESC).")],
    metric: Annotated[str, Query(description="Required, for the same reason.")],
    start: Annotated[datetime | None, Query(alias="from")] = None,
    end: Annotated[datetime | None, Query(alias="to")] = None,
    bucket_s: int | None = Query(
        default=None, ge=1, le=86400, description="Downsample to this bucket; omit for raw rows."
    ),
    limit: int = Query(default=1000, ge=1, le=20000),
    after: Annotated[
        datetime | None,
        Query(
            description="Cursor: the last row's `ts` from the previous page; returns rows after it."
        ),
    ] = None,
) -> list[dict[str, Any]]:
    """Raw telemetry is kept 90 days, then averaged to 1 minute for 2 years
    (SPEC 7 retention). A query older than the raw window silently reads the
    rollup; the returned rows carry `bucket_s` so the client knows which."""
    return list(
        await repo.query_telemetry(
            robot_id=robot_id,
            metric=metric,
            start=start,
            end=end,
            bucket_s=bucket_s,
            limit=limit,
            after=after,
        )
    )
