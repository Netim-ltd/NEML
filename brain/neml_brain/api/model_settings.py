# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Admin-screen settings per robot model and for the lab (owner-entered values)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from neml_brain.api.problem import Problem
from neml_brain.settings import catalog

router = APIRouter(prefix="/v1/model-settings", tags=["model-settings"])


class SettingsPut(BaseModel):
    values: dict[str, float | int | None] = Field(
        description="Field key -> value. A null clears the field."
    )
    actor: str = Field(min_length=1, description="Authenticated identity from the .NET API.")


def _store(request: Request) -> Any:
    return request.app.state.settings_store


@router.get("")
async def list_models(request: Request) -> list[dict[str, Any]]:
    """Every model with how many required fields are still open."""
    store = _store(request)
    out = []
    for model_id in await store.model_ids():
        view = catalog.describe(model_id, await store.get(model_id))
        out.append({"model_id": model_id, "missing_required": view["missing_required"]})
    return out


@router.get("/{model_id}")
async def get_settings(model_id: str, request: Request) -> dict[str, Any]:
    if model_id not in await _store(request).model_ids():
        raise Problem(404, "Not Found", f"No model '{model_id}'.")
    return catalog.describe(model_id, await _store(request).get(model_id))


@router.put("/{model_id}")
async def put_settings(model_id: str, body: SettingsPut, request: Request) -> dict[str, Any]:
    store = _store(request)
    if model_id not in await store.model_ids():
        raise Problem(404, "Not Found", f"No model '{model_id}'.")
    errors = catalog.validate(model_id, {k: v for k, v in body.values.items() if v is not None})
    if errors:
        raise Problem(422, "Unprocessable Entity", "; ".join(errors))
    merged = await store.put(model_id, body.values, body.actor)
    return catalog.describe(model_id, merged)
