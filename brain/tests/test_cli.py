# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""nemlctl tests (SPEC T-020). No network: httpx.request is routed to a fake."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
from typer.testing import CliRunner

from neml_brain.cli import main

runner = CliRunner()


class FakeApi:
    """Path -> (status, body) mapping; every call is recorded."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.routes: dict[tuple[str, str], tuple[int, Any]] = {}
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        monkeypatch.setattr(httpx, "request", self._handle)

    def route(self, method: str, path: str, payload: Any, status: int = 200) -> None:
        self.routes[(method, path)] = (status, payload)

    def call(self, method: str, path: str) -> dict[str, Any]:
        for recorded_method, recorded_path, kwargs in self.calls:
            if (recorded_method, recorded_path) == (method, path):
                return kwargs
        raise AssertionError(f"çağrılmadı: {method} {path} (çağrılanlar: {self.calls})")

    def _handle(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        path = urlsplit(str(url)).path
        self.calls.append((method, path, kwargs))
        status, payload = self.routes.get(
            (method, path), (404, {"title": "not found", "detail": path})
        )
        if payload is None:
            return httpx.Response(status)
        return httpx.Response(status, json=payload)


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> FakeApi:
    return FakeApi(monkeypatch)


def test_status(api: FakeApi) -> None:
    api.route(
        "GET",
        "/health",
        {
            "status": "ok",
            "model": "Qwen2.5",
            "gpu_owner": "vllm",
            "components": {"db": "up"},
        },
    )
    api.route("GET", "/v1/budget", {"llm_tokens": {"used": 1200, "limit": 500000, "ratio": 0.002}})
    result = runner.invoke(main.app, ["status"])
    assert result.exit_code == 0, result.output
    for expected in ("ok", "Qwen2.5", "vllm", "db", "llm_tokens", "500000"):
        assert expected in result.output


def test_task_list_and_filters(api: FakeApi) -> None:
    api.route("GET", "/v1/tasks", [{"id": "t1", "title": "demo", "state": "queued"}])
    result = runner.invoke(main.app, ["task", "list", "--state", "queued"])
    assert result.exit_code == 0, result.output
    assert "t1" in result.output
    assert api.call("GET", "/v1/tasks")["params"] == {"state": "queued", "limit": 50}


def test_task_create_posts_body(api: FakeApi) -> None:
    api.route("POST", "/v1/tasks", {"id": "t9"})
    result = runner.invoke(
        main.app,
        ["task", "create", "demo", "--kind", "repair", "--spec", '{"skill": "walk"}'],
    )
    assert result.exit_code == 0, result.output
    assert "t9" in result.output
    body = api.call("POST", "/v1/tasks")["json"]
    assert body["title"] == "demo"
    assert body["kind"] == "repair"
    assert body["spec"] == {"skill": "walk"}
    assert body["source"].startswith("user:")


def test_task_create_rejects_bad_json(api: FakeApi) -> None:
    result = runner.invoke(main.app, ["task", "create", "demo", "--spec", "{nope"])
    assert result.exit_code == 2
    assert not api.calls


def test_task_cancel(api: FakeApi) -> None:
    api.route("DELETE", "/v1/tasks/t1", None, status=204)
    result = runner.invoke(main.app, ["task", "cancel", "t1"])
    assert result.exit_code == 0, result.output
    api.call("DELETE", "/v1/tasks/t1")


def test_task_show_reads_the_task_then_its_runs(api: FakeApi) -> None:
    api.route("GET", "/v1/tasks/t1", {"id": "t1", "title": "demo"})
    api.route("GET", "/v1/tasks/t1/runs", [{"attempt": 1, "env": "sim", "outcome": "success"}])
    result = runner.invoke(main.app, ["task", "show", "t1"])
    assert result.exit_code == 0, result.output
    assert "demo" in result.output
    assert "success" in result.output


def test_task_show_unknown_id(api: FakeApi) -> None:
    result = runner.invoke(main.app, ["task", "show", "nope"])  # unrouted -> 404 problem
    assert result.exit_code == 1
    assert "nope" in result.output


def test_approve_list_and_show(api: FakeApi) -> None:
    api.route("GET", "/v1/approvals", [{"id": "a1", "level": 4, "subject_kind": "print"}])
    api.route("GET", "/v1/approvals/a1", {"id": "a1", "level": 4, "subject_kind": "print"})
    listed = runner.invoke(main.app, ["approve", "list"])
    assert listed.exit_code == 0, listed.output
    assert "print" in listed.output
    shown = runner.invoke(main.app, ["approve", "show", "a1"])
    assert shown.exit_code == 0, shown.output
    assert "a1" in shown.output


@pytest.mark.parametrize(("command", "decision"), [("approve", "approved"), ("reject", "rejected")])
def test_decide_sends_decision(api: FakeApi, command: str, decision: str) -> None:
    api.route("POST", "/v1/approvals/a1/decide", {"decision": decision})
    result = runner.invoke(main.app, ["approve", command, "a1", "--yes", "--note", "ok"])
    assert result.exit_code == 0, result.output
    body = api.call("POST", "/v1/approvals/a1/decide")["json"]
    assert body["decision"] == decision
    assert body["note"] == "ok"
    assert body["decided_by"]


def test_decide_aborts_without_confirmation(api: FakeApi) -> None:
    api.route("POST", "/v1/approvals/a1/decide", {})
    result = runner.invoke(main.app, ["approve", "approve", "a1"], input="n\n")
    assert result.exit_code == 1
    assert not api.calls


def test_problem_json_is_printed(api: FakeApi) -> None:
    api.route("GET", "/v1/tasks", {"title": "Budget exceeded", "detail": "llm_tokens"}, status=429)
    result = runner.invoke(main.app, ["task", "list"])
    assert result.exit_code == 1
    assert "429" in result.output
    assert "Budget exceeded" in result.output


def test_unreachable_brain_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_: Any, **__: Any) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "request", boom)
    result = runner.invoke(main.app, ["status"])
    assert result.exit_code == 2
    assert "ulaşılamadı" in result.output


def test_robot_safety_check_posts_the_attestation(api: FakeApi) -> None:
    api.route("POST", "/v1/robots/R01/safety-check", {"passed": True})
    result = runner.invoke(
        main.app,
        ["robot", "safety-check", "R01", "--estop", "--watchdog", "--current-limit", "--yes"],
    )
    assert result.exit_code == 0, result.output
    body = api.call("POST", "/v1/robots/R01/safety-check")["json"]
    assert body["estop_ok"] and body["watchdog_ok"] and body["current_limit_ok"]
    assert body["performed_by"]


def test_robot_safety_check_records_a_failure_and_says_so(api: FakeApi) -> None:
    api.route("POST", "/v1/robots/R01/safety-check", {"passed": False})
    result = runner.invoke(
        main.app,
        ["robot", "safety-check", "R01", "--estop", "--no-watchdog", "--current-limit", "--yes"],
    )
    assert result.exit_code == 0 and "BAŞARISIZ" in result.output


def test_robot_safety_check_has_no_default_for_any_flag(api: FakeApi) -> None:
    result = runner.invoke(main.app, ["robot", "safety-check", "R01", "--estop", "--yes"])
    assert result.exit_code != 0  # an attestation cannot be left half-answered
