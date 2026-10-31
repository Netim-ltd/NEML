# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""T-017 - a contract test per SPEC 8.3 endpoint.

ENDPOINTS below is the SPEC 8.3 table, transcribed row for row. Every test
iterates it, so deleting a route or changing its method fails here loudly
instead of being noticed by the mobile app in the field. The reverse check
(test_no_undeclared_routes) catches the other drift: a route that exists in
code but not in the spec.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.routing import APIRoute
from httpx import AsyncClient

from neml_brain.api.metrics import MANDATORY_METRICS
from neml_brain.api.problem import CONTENT_TYPE
from neml_brain.logging import CORRELATION_HEADER

ROBOT_ID = "R01"
TASK_ID = "11111111-1111-1111-1111-111111111111"
APPROVAL_ID = "22222222-2222-2222-2222-222222222222"
CAMPAIGN_ID = "33333333-3333-3333-3333-333333333333"

# (method, route template as FastAPI registers it, live URL, JSON body, expected status)
ENDPOINTS: list[tuple[str, str, str, dict[str, Any] | None, int]] = [
    ("GET", "/health", "/health", None, 200),
    ("GET", "/v1/robots", "/v1/robots", None, 200),
    ("GET", "/v1/robots/{robot_id}", f"/v1/robots/{ROBOT_ID}", None, 200),
    (
        "POST",
        "/v1/robots/{robot_id}/estop",
        f"/v1/robots/{ROBOT_ID}/estop",
        {"actor": "user:mg", "reason": "bench test"},
        202,
    ),
    (
        "POST",
        "/v1/robots/{robot_id}/safety-check",
        f"/v1/robots/{ROBOT_ID}/safety-check",
        {"estop_ok": True, "watchdog_ok": True, "current_limit_ok": True, "performed_by": "mg"},
        201,
    ),
    ("GET", "/v1/tasks", "/v1/tasks", None, 200),
    (
        "POST",
        "/v1/tasks",
        "/v1/tasks",
        {"title": "walk 3 m", "kind": "human", "source": "user:mg", "priority": 12.5, "spec": {}},
        201,
    ),
    ("GET", "/v1/tasks/{task_id}", f"/v1/tasks/{TASK_ID}", None, 200),
    ("PATCH", "/v1/tasks/{task_id}", f"/v1/tasks/{TASK_ID}", {"priority": 20.0}, 200),
    ("DELETE", "/v1/tasks/{task_id}", f"/v1/tasks/{TASK_ID}", None, 204),
    ("GET", "/v1/tasks/{task_id}/runs", f"/v1/tasks/{TASK_ID}/runs", None, 200),
    ("POST", "/v1/command", "/v1/command", {"text": "durum nedir", "actor": "user:mg"}, 202),
    ("GET", "/v1/skills", "/v1/skills", None, 200),
    ("GET", "/v1/genomes", "/v1/genomes", None, 200),
    ("GET", "/v1/approvals", "/v1/approvals", None, 200),
    ("GET", "/v1/approvals/{approval_id}", f"/v1/approvals/{APPROVAL_ID}", None, 200),
    (
        "POST",
        "/v1/approvals/{approval_id}/decide",
        f"/v1/approvals/{APPROVAL_ID}/decide",
        {"decision": "approved", "decided_by": "user:mg"},
        200,
    ),
    ("GET", "/v1/telemetry", "/v1/telemetry?robot_id=R01&metric=battery_soc", None, 200),
    (
        "POST",
        "/v1/sim/run",
        "/v1/sim/run",
        {"world_id": "flat_v1", "seed": 7, "profile": "fast"},
        201,
    ),
    ("GET", "/v1/model-settings", "/v1/model-settings", None, 200),
    ("GET", "/v1/model-settings/{model_id}", "/v1/model-settings/quadruped_v2", None, 200),
    (
        "PUT",
        "/v1/model-settings/{model_id}",
        "/v1/model-settings/quadruped_v2",
        {"values": {"mtbf_min_hours": 300}, "actor": "owner@firm.com"},
        200,
    ),
    ("GET", "/v1/budget", "/v1/budget", None, 200),
    ("POST", "/v1/runtime/llm/start", "/v1/runtime/llm/start", {"consumer": "sim:visual"}, 200),
    ("POST", "/v1/runtime/llm/stop", "/v1/runtime/llm/stop", {"consumer": "sim:visual"}, 200),
    ("GET", "/metrics", "/metrics", None, 200),
]

IDS = [f"{method} {template}" for method, template, *_ in ENDPOINTS]


def test_sim_physics_is_complete_and_bounded() -> None:
    """Partial or out-of-box physics must never reach the simulator."""
    from pydantic import ValidationError

    from neml_brain.api.sim import SimRunRequest

    full = {
        "friction": 0.9,
        "joint_damping": 0.2,
        "motor_gain": 1.1,
        "body_inertia_correction": 1.0,
        "comms_latency_s": 0.01,
    }
    base = {"world_id": "flat", "seed": 1}
    assert SimRunRequest.model_validate({**base, "physics": full}).physics is not None
    for bad in ({"friction": 0.9}, {**full, "friction": -1.0}, {**full, "extra": 1}):
        with pytest.raises(ValidationError, match="physics"):
            SimRunRequest.model_validate({**base, "physics": bad})


def _registered(app: Any) -> set[tuple[str, str]]:
    """Every (method, path template) the app serves, prefixes resolved.

    FastAPI wraps an included router in an opaque object rather than splicing
    its routes into app.routes, so this walks down instead of reading the top
    level.
    """
    found: set[tuple[str, str]] = set()

    def walk(routes: Any, prefix: str) -> None:
        for route in routes:
            if isinstance(route, APIRoute):
                found.update(
                    (method, prefix + route.path)
                    for method in route.methods or ()
                    if method not in ("HEAD", "OPTIONS")
                )
                continue
            included = getattr(route, "original_router", None)
            if included is not None:
                context = getattr(route, "include_context", None)
                walk(included.routes, prefix + getattr(context, "prefix", ""))
            elif getattr(route, "routes", None):
                walk(route.routes, prefix + getattr(route, "path", ""))

    walk(app.routes, "")
    return found


@pytest.mark.parametrize(("method", "template", "url", "body", "status"), ENDPOINTS, ids=IDS)
def test_spec_route_is_registered(
    app: Any, method: str, template: str, url: str, body: Any, status: int
) -> None:
    assert (method, template) in _registered(app), f"SPEC 8.3 row missing: {method} {template}"


def test_no_undeclared_routes(app: Any) -> None:
    """A route not in the SPEC 8.3 table is either spec drift or a leak."""
    declared = {(method, template) for method, template, *_ in ENDPOINTS}
    declared.update(
        {
            ("POST", "/v1/platform/ticket-request"),
            ("GET", "/v1/platform/model-bundle"),
            ("POST", "/v1/platform/model-ack"),
            ("POST", "/v1/platform/feedback"),
            ("GET", "/v1/platform/feedback-export"),
            ("POST", "/v1/platform/operation/generate"),
        }
    )
    docs = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
    extra = {(m, p) for m, p in _registered(app) if p not in docs} - declared
    assert not extra, f"routes outside SPEC 8.3: {sorted(extra)}"


@pytest.mark.parametrize(("method", "template", "url", "body", "status"), ENDPOINTS, ids=IDS)
async def test_endpoint_answers(
    client: AsyncClient, method: str, template: str, url: str, body: Any, status: int
) -> None:
    response = await client.request(method, url, json=body)
    assert response.status_code == status, response.text


@pytest.mark.parametrize(("method", "template", "url", "body", "status"), ENDPOINTS, ids=IDS)
async def test_endpoint_is_json(
    client: AsyncClient, method: str, template: str, url: str, body: Any, status: int
) -> None:
    """SPEC 8.3: all responses are application/json. /metrics is the Prometheus
    text format by definition, and 204 has no body."""
    response = await client.request(method, url, json=body)
    if url == "/metrics" or response.status_code == 204:
        return
    assert response.headers["content-type"].startswith("application/json"), url


def _assert_problem(response: Any, status: int) -> dict[str, Any]:
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith(CONTENT_TYPE)
    body = response.json()
    assert body["status"] == status
    assert isinstance(body["title"], str) and body["title"]
    assert body["type"] == "about:blank"
    assert "instance" in body
    assert body["correlation_id"]
    return dict(body)


async def test_unknown_route_is_problem_json(client: AsyncClient) -> None:
    _assert_problem(await client.get("/v1/nope"), 404)


async def test_wrong_method_is_problem_json(client: AsyncClient) -> None:
    _assert_problem(await client.delete("/v1/robots"), 405)


async def test_unknown_resource_is_problem_json(client: AsyncClient) -> None:
    body = _assert_problem(await client.get("/v1/robots/R99"), 404)
    assert "R99" in body["detail"]


async def test_validation_error_is_problem_json(client: AsyncClient) -> None:
    body = _assert_problem(await client.post("/v1/command", json={"text": ""}), 422)
    assert body["errors"], "validation problems carry the offending fields"


async def test_budget_exhaustion_is_429_problem(client: AsyncClient, app: Any) -> None:
    """SPEC 14.4 / T-018 - over the limit the request is refused, with a code
    the caller can act on, not a 500."""
    app.state.budget.allow_all = False
    body = _assert_problem(
        await client.post("/v1/command", json={"text": "tasarla", "actor": "user:mg"}), 429
    )
    assert body["resource"] == "llm_tokens"


async def test_unhandled_exception_is_problem_json(lenient_client: AsyncClient, app: Any) -> None:
    async def boom(**_: Any) -> None:
        raise RuntimeError("secret dsn in message")

    app.state.orchestrator.handle_command = boom
    response = await lenient_client.post("/v1/command", json={"text": "x", "actor": "user:mg"})
    body = _assert_problem(response, 500)
    assert "detail" not in body, "a 500 must not leak the exception message"


async def test_correlation_id_is_echoed_and_minted(client: AsyncClient) -> None:
    response = await client.get("/health", headers={CORRELATION_HEADER: "abc123"})
    assert response.headers[CORRELATION_HEADER] == "abc123"
    minted = await client.get("/v1/robots/R99")
    assert minted.json()["correlation_id"]


async def test_metrics_exposes_every_mandatory_name(client: AsyncClient) -> None:
    """SPEC 18.3 - all ten exist at zero, before anything has happened."""
    text = (await client.get("/metrics")).text
    missing = [name for name in MANDATORY_METRICS if f"# TYPE {name} " not in text]
    assert not missing, f"missing SPEC 18.3 metrics: {missing}"
    assert len(MANDATORY_METRICS) == 10


async def test_health_reports_every_mcp_server(client: AsyncClient) -> None:
    """T-016 acceptance criterion."""
    body = (await client.get("/health")).json()
    assert body["status"] == "ok"
    assert set(body["components"]) == {"db", "llm", "mcp", "bridge", "budget"}
    assert body["components"]["mcp"]["detail"]["sim"] == "ok"


async def test_health_degrades_instead_of_failing(client: AsyncClient, app: Any) -> None:
    async def down() -> None:
        raise ConnectionRefusedError("postgres")

    app.state.repo.ping = down
    body = (await client.get("/health")).json()
    assert body["status"] == "degraded"
    assert body["degraded"] == ["db"]


async def test_health_degrades_for_red_mcp_and_disconnected_bridge(
    client: AsyncClient, app: Any
) -> None:
    async def red_mcp() -> dict[str, dict[str, str]]:
        return {"sim": {"status": "red"}}

    async def offline_bridge() -> dict[str, bool]:
        return {"connected": False}

    app.state.mcp.health = red_mcp
    app.state.bridge.health = offline_bridge
    body = (await client.get("/health")).json()
    assert body["status"] == "degraded"
    assert set(body["degraded"]) == {"mcp", "bridge"}


async def test_missing_service_is_503_problem(client: AsyncClient, app: Any) -> None:
    del app.state.repo
    _assert_problem(await client.get("/v1/robots"), 503)


def test_openapi_covers_the_spec_table(app: Any) -> None:
    """T-017 also wants OpenAPI. /metrics is excluded on purpose: it is not JSON."""
    paths = app.openapi()["paths"]
    for method, template, *_ in ENDPOINTS:
        if template == "/metrics":
            continue
        assert template in paths, template
        assert method.lower() in paths[template], f"{method} {template}"
