# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Fully stubbed service layer for the SPEC 8.3 contract tests (T-017).

httpx.ASGITransport does not run the lifespan, so create_app() never imports
db/llm/mcp/agents. Everything the routers reach for is put on app.state here.
The stubs answer with the shape SPEC 7 defines and nothing more.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from neml_brain.main import create_app

ROBOT: dict[str, Any] = {
    "id": "R01",
    "genome_id": "quadruped_v2@a3f91c7",
    "namespace": "/r01",
    "hostname": "r01.lab",
    "state": "idle",
    "battery_soc": 0.87,
}
TASK = {
    "id": "11111111-1111-1111-1111-111111111111",
    "title": "walk",
    "kind": "human",
    "state": "queued",
}
APPROVAL = {"id": "22222222-2222-2222-2222-222222222222", "level": 2, "subject_kind": "task"}
CAMPAIGN = {"id": "33333333-3333-3333-3333-333333333333", "name": "gait", "state": "active"}


class StubRepo:
    async def ping(self) -> str:
        return "pg 16"

    async def list_robots(self) -> list[dict[str, Any]]:
        return [ROBOT]

    async def get_robot(self, robot_id: str) -> dict[str, Any] | None:
        return ROBOT if robot_id == ROBOT["id"] else None

    async def list_tasks(self, **_: Any) -> list[dict[str, Any]]:
        return [TASK]

    async def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {**TASK, **payload}

    async def update_task(self, task_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        return {**TASK, **changes} if task_id == TASK["id"] else None

    async def cancel_task(self, task_id: str) -> bool:
        return task_id == TASK["id"]

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        return TASK if task_id == TASK["id"] else None

    async def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        return APPROVAL if approval_id == APPROVAL["id"] else None

    async def list_task_runs(self, task_id: str) -> list[dict[str, Any]] | None:
        return [{"task_id": task_id, "attempt": 1, "env": "sim", "outcome": "success"}]

    async def list_skills(self, **_: Any) -> list[dict[str, Any]]:
        return [{"id": "climb_small_obstacle@3", "status": "validated"}]

    async def genome_lineage(self, **_: Any) -> list[dict[str, Any]]:
        return [{"id": "quadruped_v2@a3f91c7", "parent_id": None, "status": "active"}]

    async def pending_approvals(self) -> list[dict[str, Any]]:
        return [APPROVAL]

    async def query_telemetry(self, **_: Any) -> list[dict[str, Any]]:
        return [{"ts": "2026-09-16T10:00:00Z", "metric": "battery_soc", "value": 0.87}]

    async def ensure_telemetry_partitions(self) -> None:
        return None


class StubSettings:
    def __init__(self) -> None:
        self.stored: dict[str, Any] = {}

    async def model_ids(self) -> list[str]:
        return ["_lab", "quadruped_v2"]

    async def get(self, model_id: str) -> dict[str, Any]:
        return dict(self.stored.get(model_id, {}))

    async def put(self, model_id: str, values: dict[str, Any], actor: str) -> dict[str, Any]:
        merged = {**self.stored.get(model_id, {}), **values}
        self.stored[model_id] = {k: v for k, v in merged.items() if v is not None}
        return self.stored[model_id]


class StubLlm:
    async def ping(self) -> str:
        return "Qwen/Qwen2.5-Coder-1.5B-Instruct-AWQ"


class StubMcp:
    async def health(self) -> dict[str, str]:
        servers = ("sim", "fab", "genome", "freecad", "kicad", "postgres", "filesystem", "git")
        return dict.fromkeys(servers, "ok")


class StubBridge:
    async def health(self) -> dict[str, Any]:
        return {"connected": True, "queued": 0}


class StubBudget:
    allow_all = True

    async def allow(self, resource: str) -> bool:
        return self.allow_all

    async def snapshot(self) -> dict[str, Any]:
        return {"resources": {"llm_tokens": {"used": 1000, "limit": 500000, "ratio": 0.002}}}

    async def reset_daily(self) -> None:
        return None


class StubSafety:
    async def software_estop(self, robot_id: str, actor: str, reason: str) -> dict[str, Any] | None:
        if robot_id != ROBOT["id"]:
            return None
        return {"state": "estop", "actor": actor, "reason": reason}

    async def decide_approval(
        self, approval_id: str, decision: str, **_: Any
    ) -> dict[str, Any] | None:
        return {**APPROVAL, "decision": decision} if approval_id == APPROVAL["id"] else None

    async def record_safety_check(self, *, robot_id: str, **checks: Any) -> dict[str, Any] | None:
        if robot_id != ROBOT["id"]:
            return None
        return {
            "robot_id": robot_id,
            **checks,
            "passed": all(v for k, v in checks.items() if k.endswith("_ok")),
        }

    async def expire_approvals(self) -> int:
        return 0


class StubGpuLock:
    async def acquire(self, consumer: str, timeout_s: float = 300.0) -> float:
        return 0.0

    async def release(self, consumer: str) -> bool:
        return True


class StubSim:
    async def run_once(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"sim_run_id": 1, "outcome": "success", "metrics": {}, **payload}


class StubOrchestrator:
    async def handle_command(self, **kwargs: Any) -> dict[str, Any]:
        return {"intent": "query_status", "accepted": True, **kwargs}


class StubEvolution:
    async def start_campaign(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {**CAMPAIGN, **payload}

    async def list_campaigns(self, **_: Any) -> list[dict[str, Any]]:
        return [CAMPAIGN]

    async def campaign_progress(self, campaign_id: str) -> dict[str, Any] | None:
        return {**CAMPAIGN, "generations": []} if campaign_id == CAMPAIGN["id"] else None

    async def stop_campaign(self, campaign_id: str, **_: Any) -> dict[str, Any] | None:
        return {**CAMPAIGN, "state": "stopped"} if campaign_id == CAMPAIGN["id"] else None


@pytest.fixture
def app() -> Any:
    application = create_app()
    state = application.state
    state.repo = StubRepo()
    state.llm = StubLlm()
    state.settings_store = StubSettings()
    state.mcp = StubMcp()
    state.bridge = StubBridge()
    state.budget = StubBudget()
    state.safety = StubSafety()
    state.gpu_lock = StubGpuLock()
    state.sim = StubSim()
    state.orchestrator = StubOrchestrator()
    state.evolution = StubEvolution()
    return application


@pytest.fixture
async def client(app: Any) -> AsyncIterator[AsyncClient]:
    """Strict: an exception escaping a router propagates into the test, so a
    bug shows up as a traceback and not as an opaque 500."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://brain") as http:
        yield http


@pytest.fixture
async def lenient_client(app: Any) -> AsyncIterator[AsyncClient]:
    """Lets the 500 handler's response through, for the one test that asserts it."""
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://brain") as http:
        yield http
