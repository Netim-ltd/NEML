# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the shared MCP transport and subprocess runner (SPEC 6.2).

`run_cli` is the SPEC 1.3 boundary: every third-party tool is a separate
process, so a hang or a non-zero exit must surface as a typed error instead of
propagating into the daemon.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mcp_servers._common import CliFailed, CliTimeout, make_app, run_cli


def call(coro: Any) -> Any:
    """No pytest-asyncio outside brain/: drive the coroutine directly."""
    return asyncio.run(coro)


def test_run_cli_returns_stdout() -> None:
    out = call(run_cli([sys.executable, "-c", "print('ok')"], 30.0))
    assert out.strip() == "ok"


def test_run_cli_non_zero_exit_raises_cli_failed() -> None:
    with pytest.raises(CliFailed) as err:
        call(
            run_cli(
                [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"], 30.0
            )
        )
    assert "exited 3" in str(err.value)
    assert "boom" in str(err.value)


def test_run_cli_timeout_kills_the_process() -> None:
    with pytest.raises(CliTimeout):
        call(run_cli([sys.executable, "-c", "import time; time.sleep(30)"], 0.2))


# --- Streamable HTTP envelope ----------------------------------------------


async def add(a: int, b: int = 2) -> dict[str, int]:
    """Add two numbers."""
    return {"sum": a + b}


def boom() -> None:
    """Always fails."""
    raise ValueError("nope")


@pytest.fixture
def client() -> TestClient:
    return TestClient(make_app("neml-mcp-test", "1.0.0", {"add": add, "boom": boom}))


def post(client: TestClient, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    return dict(client.post("/mcp", json=body).json())


def test_initialize_reports_the_protocol_version(client: TestClient) -> None:
    result = post(client, "initialize")["result"]
    assert result["serverInfo"]["name"] == "neml-mcp-test"
    assert result["protocolVersion"]


def test_tools_list_derives_the_input_schema(client: TestClient) -> None:
    tools = {t["name"]: t for t in post(client, "tools/list")["result"]["tools"]}
    assert tools["add"]["description"] == "Add two numbers."
    schema = tools["add"]["inputSchema"]
    assert schema["properties"]["a"]["type"] == "integer"
    assert schema["required"] == ["a"]  # `b` has a default


def test_tools_call_awaits_and_encodes_the_result(client: TestClient) -> None:
    result = post(client, "tools/call", {"name": "add", "arguments": {"a": 3, "b": 4}})["result"]
    assert result == {"structuredContent": {"sum": 7}, "isError": False}


def test_unknown_tool_is_a_typed_error(client: TestClient) -> None:
    error = post(client, "tools/call", {"name": "nope", "arguments": {}})["error"]
    assert error["code"] == -32000
    assert "unknown tool" in error["message"]


def test_tool_exception_becomes_a_typed_error(client: TestClient) -> None:
    error = post(client, "tools/call", {"name": "boom", "arguments": {}})["error"]
    assert error["message"].startswith("ValueError:")


def test_unknown_method_is_refused(client: TestClient) -> None:
    assert post(client, "tools/nope")["error"]["code"] == -32601


def test_notifications_are_accepted_without_a_body(client: TestClient) -> None:
    response = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert response.status_code == 202
