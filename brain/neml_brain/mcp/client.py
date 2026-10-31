# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Streamable HTTP MCP client (SPEC 6.2 / 6.5).

MCP calls are issued deterministically by LangGraph nodes. The model never sees
this server list and never picks a tool (SPEC 6.5).

ponytail: no MCP SDK dependency - the spec's dependency list (SPEC 8.1) names
httpx and nothing else, and Streamable HTTP is a single JSON-RPC POST with an
optional SSE reply. If we ever need sessions, resumable streams or server->client
sampling, swap this module for the official SDK; call sites only use
`McpClient.call` / `McpClient.list_tools`.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx
import yaml

from neml_brain.paths import CONFIG_DIR

CONFIG_PATH = CONFIG_DIR / "mcp.yaml"

_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": "2025-06-18",
}


class McpError(Exception):
    """Base for every MCP failure. Callers never get a bare dict back."""


class McpConfigError(McpError):
    """config/mcp.yaml is missing the server or a required key."""


class McpTransportError(McpError):
    """Connection refused, bad status, unparsable body - retries exhausted."""


class McpTimeoutError(McpError):
    """Server did not answer inside the configured timeout."""


class McpToolError(McpError):
    """Server answered with a JSON-RPC error object."""

    def __init__(self, message: str, code: int = -32000, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.data = data


class McpPermissionError(McpError):
    """Argument violates the server's own config (SPEC 6.5 allowed_paths)."""


@dataclass(frozen=True)
class ServerConfig:
    """One entry of the `servers` map in config/mcp.yaml."""

    name: str
    url: str
    timeout_s: float
    retries: int = 0
    role: str | None = None  # enforced by the Postgres GRANT, not by this client
    allowed_paths: tuple[str, ...] = ()
    optional: bool = False  # an unreachable optional server is "off", not red


def load_servers(path: Path = CONFIG_PATH) -> dict[str, ServerConfig]:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))["servers"]
    except (OSError, KeyError, yaml.YAMLError) as exc:
        raise McpConfigError(f"cannot read MCP config {path}: {exc}") from exc
    out: dict[str, ServerConfig] = {}
    for name, cfg in raw.items():
        try:
            out[name] = ServerConfig(
                name=name,
                url=os.getenv(f"NEML_MCP_URL_{name.upper().replace('-', '_')}", cfg["url"]),
                timeout_s=float(cfg["timeout_s"]),
                retries=int(cfg.get("retries", 0)),
                role=cfg.get("role"),
                allowed_paths=tuple(cfg.get("allowed_paths", ())),
                optional=bool(cfg.get("optional", False)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise McpConfigError(f"bad MCP server entry '{name}': {exc}") from exc
    return out


def _check_paths(cfg: ServerConfig, arguments: dict[str, Any]) -> None:
    """SPEC 6.5: the filesystem server is fenced to allowed_paths."""
    if not cfg.allowed_paths:
        return
    candidates: list[str] = []
    for key in ("path", "paths", "src", "dst"):
        value = arguments.get(key)
        if isinstance(value, str):
            candidates.append(value)
        elif isinstance(value, (list, tuple)):
            candidates.extend(str(item) for item in value)
    for candidate in candidates:
        if not any(
            candidate == root or candidate.startswith(root + "/") for root in cfg.allowed_paths
        ):
            raise McpPermissionError(
                f"{cfg.name}: '{candidate}' is outside {list(cfg.allowed_paths)}"
            )


class McpClient:
    """One client for every configured server."""

    def __init__(
        self,
        servers: dict[str, ServerConfig] | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.servers = servers if servers is not None else load_servers()
        self._http = http or httpx.AsyncClient()
        self._ids = itertools.count(1)

    async def aclose(self) -> None:
        await self._http.aclose()

    def config(self, server: str) -> ServerConfig:
        try:
            return self.servers[server]
        except KeyError as exc:
            raise McpConfigError(f"unknown MCP server '{server}'") from exc

    async def call(
        self,
        server: str,
        tool: str,
        arguments: dict[str, Any] | None = None,
        timeout_s: float | None = None,
    ) -> Any:
        cfg = self.config(server)
        arguments = arguments or {}
        _check_paths(cfg, arguments)
        result = await self._rpc(
            cfg, "tools/call", {"name": tool, "arguments": arguments}, timeout_s
        )
        if isinstance(result, dict) and "structuredContent" in result:
            return result["structuredContent"]
        return result

    async def list_tools(self, server: str, timeout_s: float | None = None) -> list[dict[str, Any]]:
        result = await self._rpc(self.config(server), "tools/list", {}, timeout_s)
        return list(result.get("tools", [])) if isinstance(result, dict) else []

    async def _rpc(
        self, cfg: ServerConfig, method: str, params: dict[str, Any], timeout_s: float | None
    ) -> Any:
        timeout = cfg.timeout_s if timeout_s is None else timeout_s
        payload = {"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params}
        last: McpError = McpTransportError(f"{cfg.name}: no attempt made")
        # retries == 0 for `sim` on purpose: re-running a simulation is not idempotent.
        for attempt in range(cfg.retries + 1):
            try:
                response = await self._http.post(
                    cfg.url, json=payload, headers=_HEADERS, timeout=timeout
                )
                response.raise_for_status()
                return _unwrap(_decode(cfg, response))
            except httpx.TimeoutException:
                last = McpTimeoutError(f"{cfg.name}: {method} timed out after {timeout}s")
            except httpx.HTTPError as exc:
                last = McpTransportError(f"{cfg.name}: {method} failed: {exc}")
            if attempt < cfg.retries:
                await asyncio.sleep(0.5 * (attempt + 1))
        raise last


def _decode(cfg: ServerConfig, response: httpx.Response) -> dict[str, Any]:
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        for line in response.text.splitlines():
            if line.startswith("data:"):
                message = _as_object(cfg, line[5:].strip())
                if "result" in message or "error" in message:
                    return message
        raise McpTransportError(f"{cfg.name}: SSE stream carried no JSON-RPC response")
    return _as_object(cfg, response.text)


def _as_object(cfg: ServerConfig, raw: str) -> dict[str, Any]:
    try:
        message = json.loads(raw)
    except ValueError as exc:
        raise McpTransportError(f"{cfg.name}: non-JSON response: {exc}") from exc
    if not isinstance(message, dict):
        raise McpTransportError(f"{cfg.name}: JSON-RPC response must be an object")
    return cast(dict[str, Any], message)


def _unwrap(message: dict[str, Any]) -> Any:
    error = message.get("error")
    if error:
        raise McpToolError(
            str(error.get("message", "unknown MCP error")),
            code=int(error.get("code", -32000)),
            data=error.get("data"),
        )
    return message.get("result")
