# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Task CRUD and run history (SPEC 8.3, schema in SPEC 7)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from neml_brain.api import deps
from neml_brain.api.metrics import TASK_QUEUE_DEPTH
from neml_brain.api.problem import Problem

router = APIRouter(prefix="/v1/tasks", tags=["tasks"])

TaskKind = Literal["human", "repair", "exploration", "evolution", "maintenance", "calibration"]
TaskState = Literal[
    "queued",
    "planning",
    "awaiting_approval",
    "running",
    "paused",
    "succeeded",
    "failed",
    "cancelled",
]
OPEN_STATES = {"queued", "planning", "awaiting_approval", "running", "paused"}


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    kind: TaskKind
    source: str = Field(min_length=1, description="user:mg | auto:failure | auto:coverage")
    priority: float = Field(ge=0, le=999.999, description="SPEC 14.2 formula output.")
    spec: dict[str, Any]
    robot_id: str | None = None
    deadline: datetime | None = None


class TaskPatch(BaseModel):
    """SPEC 8.3: priority, spec and state are the updatable fields."""

    priority: float | None = Field(default=None, ge=0, le=999.999)
    spec: dict[str, Any] | None = None
    state: TaskState | None = None


@router.get("")
async def list_tasks(
    repo: deps.Repo,
    state: TaskState | None = None,
    kind: TaskKind | None = None,
    robot_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = await repo.list_tasks(
        state=state, kind=kind, robot_id=robot_id, limit=limit, offset=offset
    )
    if state is None and offset == 0:
        TASK_QUEUE_DEPTH.set(sum(1 for task in tasks if task.get("state") in OPEN_STATES))
    return tasks


@router.post("", status_code=201)
async def create_task(body: TaskCreate, repo: deps.Repo) -> dict[str, Any]:
    return dict(await repo.create_task(body.model_dump(mode="json")))


@router.get("/{task_id}")
async def get_task(task_id: str, repo: deps.Repo) -> dict[str, Any]:
    task = await repo.get_task(task_id)
    if task is None:
        raise Problem(404, "Not Found", f"No task with id '{task_id}'.")
    return dict(task)


@router.patch("/{task_id}")
async def update_task(task_id: str, body: TaskPatch, repo: deps.Repo) -> dict[str, Any]:
    changes = body.model_dump(mode="json", exclude_unset=True)
    if not changes:
        raise Problem(422, "Unprocessable Entity", "Send at least one of: priority, spec, state.")
    task = await repo.update_task(task_id, changes)
    if task is None:
        raise Problem(404, "Not Found", f"No task with id '{task_id}'.")
    return dict(task)


@router.delete("/{task_id}", status_code=204, response_model=None)
async def cancel_task(task_id: str, repo: deps.Repo) -> None:
    """Cancel, not delete: SPEC 7 keeps the row with state `cancelled`."""
    if not await repo.cancel_task(task_id):
        raise Problem(404, "Not Found", f"No task with id '{task_id}'.")


@router.get("/{task_id}/runs")
async def task_runs(task_id: str, repo: deps.Repo) -> list[dict[str, Any]]:
    runs = await repo.list_task_runs(task_id)
    if runs is None:
        raise Problem(404, "Not Found", f"No task with id '{task_id}'.")
    return list(runs)
