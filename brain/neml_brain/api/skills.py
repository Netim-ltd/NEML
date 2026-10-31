# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""GET /v1/skills — the skill library (SPEC 8.3, schema in SPEC 7)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query

from neml_brain.api import deps

router = APIRouter(prefix="/v1/skills", tags=["skills"])


@router.get("")
async def list_skills(
    repo: deps.Repo,
    skill_key: str | None = None,
    status: Literal["candidate", "validated", "retired"] | None = None,
    genome_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[dict[str, Any]]:
    """Latest validation stats come with each row; SPEC 14.6 drops a skill
    below 70% success into an automatic repair task."""
    return list(
        await repo.list_skills(skill_key=skill_key, status=status, genome_id=genome_id, limit=limit)
    )
