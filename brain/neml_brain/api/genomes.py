# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""GET /v1/genomes — the genome lineage tree (SPEC 8.3)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter

from neml_brain.api import deps

router = APIRouter(prefix="/v1/genomes", tags=["genomes"])


@router.get("")
async def genome_lineage(
    repo: deps.Repo,
    root_id: str | None = None,
    status: Literal["draft", "testing", "active", "deprecated"] | None = None,
) -> list[dict[str, Any]]:
    """Flat rows carrying `parent_id`; the client draws the tree. Sending a
    nested structure would only move the same join into the server."""
    return list(await repo.genome_lineage(root_id=root_id, status=status))
