# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The one helper the four NEML MCP servers share (SPEC 6.2).

Streamable HTTP transport (not stdio) plus a subprocess runner. Nothing else is
shared between the servers on purpose: they are separate daemons on separate
ports with separate failure domains.
"""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import typing
from collections.abc import Callable
from typing import Any, cast

from fastapi import FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

PROTOCOL_VERSION = "2025-06-18"

_JSON_TYPES: dict[Any, str] = {
    int: "integer",
    float: "number",
    bool: "boolean",
    str: "string",
    list: "array",
    dict: "object",
}


class CliTimeout(RuntimeError):
    """External tool did not finish inside the caller's timeout."""


class CliFailed(RuntimeError):
    """External tool exited non-zero."""


async def run_cli(argv: list[str], timeout_s: float) -> str:
    """Run an external tool as a separate process and return stdout.

    Every third-party tool in NEML (PrusaSlicer, freecadcmd, gz) is invoked this
    way - never linked, never embedded (SPEC 1.3).
    """
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise CliTimeout(f"{argv[0]} exceeded {timeout_s}s") from exc
    if proc.returncode != 0:
        raise CliFailed(
            f"{argv[0]} exited {proc.returncode}: {err.decode(errors='replace').strip()}"
        )
    return out.decode(errors="replace")


def _signature(fn: Callable[..., Any]) -> inspect.Signature:
    return inspect.signature(fn, eval_str=True)


def _input_schema(fn: Callable[..., Any]) -> dict[str, Any]:
    props: dict[str, Any] = {}
    required: list[str] = []
    for name, param in _signature(fn).parameters.items():
        annotation = param.annotation
        origin = typing.get_origin(annotation) or annotation
        props[name] = {"type": _JSON_TYPES.get(origin, "object")}
        if param.default is inspect.Parameter.empty:
            required.append(name)
    return {"type": "object", "properties": props, "required": required}


def _coerce(fn: Callable[..., Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """JSON objects -> the dataclasses the contract declares."""
    out = dict(arguments)
    for name, param in _signature(fn).parameters.items():
        annotation = param.annotation
        if dataclasses.is_dataclass(annotation) and isinstance(out.get(name), dict):
            # is_dataclass() narrows to DataclassInstance, which mypy will not call;
            # here the annotation is the dataclass TYPE, so calling it is correct.
            out[name] = cast("Any", annotation)(**out[name])
    return out


def make_app(name: str, version: str, tools: dict[str, Callable[..., Any]]) -> FastAPI:
    """A Streamable HTTP MCP endpoint at POST /mcp over the given tool table."""
    app = FastAPI(title=name, version=version, docs_url=None, redoc_url=None)

    @app.post("/mcp")
    async def mcp(request: Request) -> Response:  # noqa: C901 - one flat dispatch
        message = await request.json()
        request_id = message.get("id")
        method = message.get("method")
        try:
            if method == "initialize":
                result: Any = {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": name, "version": version},
                }
            elif method == "tools/list":
                result = {
                    "tools": [
                        {
                            "name": tool_name,
                            "description": (fn.__doc__ or "").strip().splitlines()[0]
                            if fn.__doc__
                            else "",
                            "inputSchema": _input_schema(fn),
                        }
                        for tool_name, fn in tools.items()
                    ]
                }
            elif method == "tools/call":
                params = message.get("params") or {}
                tool_name = str(params.get("name", ""))
                fn = tools.get(tool_name)
                if fn is None:
                    raise KeyError(f"unknown tool '{tool_name}'")
                value = fn(**_coerce(fn, params.get("arguments") or {}))
                if inspect.isawaitable(value):
                    value = await value
                result = {"structuredContent": jsonable_encoder(value), "isError": False}
            elif isinstance(method, str) and method.startswith("notifications/"):
                return Response(status_code=202)
            else:
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32601, "message": f"unknown method '{method}'"},
                    }
                )
        except Exception as exc:  # typed error in, typed error out (SPEC 6.3)
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32000, "message": f"{type(exc).__name__}: {exc}"},
                }
            )
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})

    return app
