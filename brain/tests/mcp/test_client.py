# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""MCP client + health registry (SPEC 6.5, acceptance T-016)."""

import json

import httpx
import pytest

from neml_brain.mcp import client as mcp_client
from neml_brain.mcp import registry
from neml_brain.mcp.client import (
    McpClient,
    McpPermissionError,
    McpTimeoutError,
    McpToolError,
    ServerConfig,
    load_servers,
)


@pytest.fixture(autouse=True)
def no_backoff_sleep(monkeypatch):
    async def instant(_seconds):
        return None

    monkeypatch.setattr(mcp_client.asyncio, "sleep", instant)


def _client(handler, **overrides) -> McpClient:
    servers = {
        "sim": ServerConfig("sim", "http://127.0.0.1:9101/mcp", 600, 0),
        "genome": ServerConfig("genome", "http://127.0.0.1:9103/mcp", 30, 2),
        "filesystem": ServerConfig(
            "filesystem",
            "http://127.0.0.1:9107/mcp",
            30,
            2,
            allowed_paths=("/srv/neml/work", "/srv/neml/artifacts"),
        ),
    }
    servers.update(overrides)
    return McpClient(
        servers=servers, http=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


def test_config_file_matches_spec_6_5():
    servers = load_servers()
    assert servers["sim"].url == "http://127.0.0.1:9101/mcp"
    assert servers["sim"].timeout_s == 600 and servers["sim"].retries == 0  # not idempotent
    assert servers["fab"].timeout_s == 120 and servers["fab"].retries == 1
    assert servers["postgres"].role == "readonly"
    assert servers["filesystem"].allowed_paths == ("/srv/neml/work", "/srv/neml/artifacts")
    assert set(servers) == {
        "freecad",
        "kicad",
        "sim",
        "fab",
        "genome",
        "postgres",
        "filesystem",
        "git",
        "blender",
        "fetch",
    }
    assert servers["fetch"].optional and not servers["sim"].optional


async def test_call_returns_structured_content():
    def handler(request):
        body = json.loads(request.content)
        assert body["method"] == "tools/call"
        assert body["params"]["name"] == "get_metrics"
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": body["id"], "result": {"structuredContent": {"seed": 7}}},
        )

    assert await _client(handler).call("sim", "get_metrics", {"robot": {}}) == {"seed": 7}


async def test_sse_response_is_decoded():
    def handler(request):
        body = json.loads(request.content)
        payload = json.dumps(
            {"jsonrpc": "2.0", "id": body["id"], "result": {"tools": [{"name": "x"}]}}
        )
        return httpx.Response(
            200,
            text=f"event: message\ndata: {payload}\n\n",
            headers={"content-type": "text/event-stream"},
        )

    assert await _client(handler).list_tools("sim") == [{"name": "x"}]


async def test_server_error_becomes_a_typed_exception():
    def handler(request):
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "error": {"code": -32000, "message": "SimStateError: no world"},
            },
        )

    with pytest.raises(McpToolError) as exc:
        await _client(handler).call("sim", "step", {"duration_s": 1.0})
    assert exc.value.code == -32000


async def test_retries_follow_the_config():
    attempts = {"sim": 0, "genome": 0}

    def handler(request):
        name = "sim" if ":9101" in str(request.url) else "genome"
        attempts[name] += 1
        raise httpx.ReadTimeout("slow", request=request)

    client = _client(handler)
    with pytest.raises(McpTimeoutError):
        await client.call("sim", "step", {"duration_s": 1.0})
    with pytest.raises(McpTimeoutError):
        await client.call("genome", "read", {"genome_id": "x"})
    assert attempts == {"sim": 1, "genome": 3}  # sim never re-runs; genome retries twice


async def test_filesystem_paths_are_fenced():
    def handler(request):
        body = json.loads(request.content)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})

    client = _client(handler)
    await client.call("filesystem", "read_file", {"path": "/srv/neml/work/a.txt"})
    with pytest.raises(McpPermissionError):
        await client.call("filesystem", "read_file", {"path": "/etc/shadow"})


async def test_health_snapshot_reports_green_and_red():
    def handler(request):
        if ":9103" in str(request.url):
            raise httpx.ConnectError("connection refused", request=request)
        body = json.loads(request.content)
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"tools": [{"name": "step"}]}}
        )

    snapshot = await registry.health_snapshot(_client(handler))
    assert snapshot["sim"]["status"] == "green" and snapshot["sim"]["tools"] == 1
    assert (
        snapshot["genome"]["status"] == "red"
        and "connection refused" in snapshot["genome"]["detail"]
    )
    assert set(snapshot) == {"sim", "genome", "filesystem"}  # every configured server is reported
    assert registry.all_green(snapshot) is False
