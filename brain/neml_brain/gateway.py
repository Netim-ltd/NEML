# ruff: noqa: E501, B008
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""An OpenAI-compatible door to the lab's language model and embedder, for the owner's customers and other systems.

`/v1/chat/completions` goes to the llama.cpp server (streaming included), `/v1/embeddings` to the embed service
(384-dimension vectors), `/v1/models` names what is served, `/v1/usage` tells a client its own limits and today's use.

Every call needs `Authorization: Bearer <key>`. Keys belong to clients, listed in the clients file
(`NEML_GATEWAY_CLIENTS`, default /var/lib/neml/gateway/clients.json, re-read when it changes, so limits move without a restart):

    {"clients": [{"name": "neml", "key": "<24+ chars>", "max_tokens": 8192, "daily_tokens": 0, "priority": 0},
                 {"name": "customer-a", "key": "...", "max_tokens": 512, "daily_tokens": 100000, "priority": 5}]}

* max_tokens   - the most a single answer may have (the request's own max_tokens is cut to it);
* daily_tokens - prompt + answer tokens per UTC day, 0 = unlimited; past it the client gets 429 until midnight;
* priority     - who goes first when several wait for the model (lower first); the model serves one outside call at a time.

With no clients file, the keys of `NEML_GATEWAY_KEYS` (comma separated) become clients with the default limits. With neither, the
gateway refuses everything. Usage is kept per client and day in usage.json next to the clients file.

# ponytail: one shared model slot with a priority queue, daily quotas only; add per-minute rates when a client needs them."""

from __future__ import annotations

import asyncio
import heapq
import hmac
import itertools
import json
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

LLM_URL = os.environ.get("NEML_GATEWAY_LLM", "http://llm:8080")
EMBED_URL = os.environ.get("NEML_GATEWAY_EMBED", "http://embed:8081")
MODEL_NAME = os.environ.get("NEML_MODEL", "neml-main")
EMBED_MODEL = "neml-embed"
DEFAULT_MAX_TOKENS = int(os.environ.get("NEML_GATEWAY_MAX_TOKENS", "2048"))
ANSWER_DEFAULT = 2048  # an answer asks for this many tokens when the request names none (cut to the client's maximum)
MAX_BODY = 512 * 1024
MAX_TEXTS = 64
MIN_KEY = 16

app = FastAPI(title="NEML gateway", docs_url=None, redoc_url=None)


@dataclass(frozen=True)
class Client:
    name: str
    key: str
    max_tokens: int = DEFAULT_MAX_TOKENS
    daily_tokens: int = 0
    priority: int = 10


def state_dir() -> Path:
    return Path(os.environ.get("NEML_GATEWAY_DIR", "/var/lib/neml/gateway"))


def clients_file() -> Path:
    return Path(os.environ.get("NEML_GATEWAY_CLIENTS", str(state_dir() / "clients.json")))


_cache: dict[str, Any] = {"stamp": None, "clients": []}


def clients() -> list[Client]:
    path = clients_file()
    try:
        stamp: Any = (path.stat().st_mtime_ns, os.environ.get("NEML_GATEWAY_KEYS", ""))
    except OSError:
        stamp = (None, os.environ.get("NEML_GATEWAY_KEYS", ""))
    if _cache["stamp"] == stamp:
        return _cache["clients"]
    found: list[Client] = []
    try:
        for row in json.loads(path.read_text(encoding="utf-8")).get("clients", []):
            if isinstance(row, dict) and len(str(row.get("key", ""))) >= MIN_KEY and row.get("name"):
                found.append(
                    Client(
                        str(row["name"]),
                        str(row["key"]),
                        max(int(row.get("max_tokens", DEFAULT_MAX_TOKENS)), 1),
                        max(int(row.get("daily_tokens", 0)), 0),
                        int(row.get("priority", 10)),
                    )
                )
    except (OSError, ValueError, AttributeError):
        pass
    if not found:  # no usable file: the plain keys of the environment, default limits
        found = [Client(f"key{i + 1}", k.strip()) for i, k in enumerate(os.environ.get("NEML_GATEWAY_KEYS", "").split(",")) if len(k.strip()) >= MIN_KEY]
    _cache.update(stamp=stamp, clients=found)
    return found


async def authorised(authorization: str = Header(default="")) -> Client:
    token = authorization.removeprefix("Bearer ").strip()
    for c in clients():
        if token and hmac.compare_digest(token, c.key):
            return c
    raise HTTPException(401, "invalid or missing API key")


# ---------------------------------------------------------------- usage
def today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def usage_book() -> dict[str, Any]:
    try:
        return json.loads((state_dir() / "usage.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def used_today(client: Client) -> dict[str, int]:
    return usage_book().get(today(), {}).get(client.name, {"prompt": 0, "completion": 0, "requests": 0})


def record(client: Client, prompt: int, completion: int) -> None:
    book = usage_book()
    book = {today(): book.get(today(), {})}  # yesterday is dropped: the book only holds today
    row = book[today()].setdefault(client.name, {"prompt": 0, "completion": 0, "requests": 0})
    row["prompt"] += prompt
    row["completion"] += completion
    row["requests"] += 1
    try:
        state_dir().mkdir(parents=True, exist_ok=True)
        tmp = state_dir() / "usage.json.tmp"
        tmp.write_text(json.dumps(book), encoding="utf-8")
        tmp.replace(state_dir() / "usage.json")
    except OSError:
        pass  # a lost counter must never fail the answer


def check_quota(client: Client) -> None:
    if client.daily_tokens:
        row = used_today(client)
        if row["prompt"] + row["completion"] >= client.daily_tokens:
            raise HTTPException(429, f"daily token quota of {client.daily_tokens} used up; it resets at 00:00 UTC")


# ---------------------------------------------------------------- one model slot, served by priority
class Gate:
    """The model serves one outside call at a time; the waiting client with the lowest priority number goes first."""

    def __init__(self) -> None:
        self._busy = False
        self._queue: list[tuple[int, int, asyncio.Future[None]]] = []
        self._order = itertools.count()

    async def acquire(self, priority: int) -> None:
        if not self._busy:
            self._busy = True
            return
        fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        entry = (priority, next(self._order), fut)
        heapq.heappush(self._queue, entry)
        try:
            await fut
        except BaseException:
            if not fut.done() or fut.cancelled():
                self._queue = [e for e in self._queue if e is not entry]
                heapq.heapify(self._queue)
            else:  # it was handed the slot just as it gave up
                self.release()
            raise

    def release(self) -> None:
        while self._queue:
            _, _, fut = heapq.heappop(self._queue)
            if not fut.done():
                fut.set_result(None)
                return
        self._busy = False


gate = Gate()


def client_http() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(1800.0, connect=10.0))


async def body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise HTTPException(413, "request too large")
    try:
        data = await request.json()
    except ValueError as exc:
        raise HTTPException(400, "body must be JSON") from exc
    if not isinstance(data, dict):
        raise HTTPException(400, "body must be a JSON object")
    return data


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "clients": len(clients())}


@app.get("/v1/models")
async def models(client: Client = Depends(authorised)) -> dict[str, Any]:
    return {"object": "list", "data": [{"id": MODEL_NAME, "object": "model"}, {"id": EMBED_MODEL, "object": "model"}]}


@app.get("/v1/usage")
async def usage(client: Client = Depends(authorised)) -> dict[str, Any]:
    row = used_today(client)
    return {
        "client": client.name,
        "max_tokens": client.max_tokens,
        "daily_tokens": client.daily_tokens,
        "priority": client.priority,
        "today": {**row, "total": row["prompt"] + row["completion"]},
    }


def sse_usage(tail: bytes) -> tuple[int, int]:
    """The usage the llama.cpp server sends in its last event (we ask for it); (0, 0) when it did not."""
    for line in reversed(tail.decode("utf-8", "replace").splitlines()):
        if line.startswith("data:") and '"usage"' in line:
            try:
                u = json.loads(line[5:]).get("usage") or {}
                return int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0))
            except (ValueError, AttributeError):
                return 0, 0
    return 0, 0


@app.post("/v1/chat/completions", response_model=None)
async def chat(data: dict[str, Any] = Depends(body), client: Client = Depends(authorised)) -> Any:
    if not isinstance(data.get("messages"), list) or not data["messages"]:
        raise HTTPException(400, "messages is required")
    check_quota(client)
    asked = data.get("max_tokens") or data.get("max_completion_tokens") or min(ANSWER_DEFAULT, client.max_tokens)
    data["max_tokens"] = max(1, min(int(asked), client.max_tokens))
    data.pop("max_completion_tokens", None)
    data.pop("model", None)  # one model is resident
    if not data.get("stream"):
        await gate.acquire(client.priority)
        try:
            async with client_http() as http:
                r = await http.post(f"{LLM_URL}/v1/chat/completions", json=data)
        finally:
            gate.release()
        out = r.json()
        u = out.get("usage") or {}
        record(client, int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0)))
        return JSONResponse(out, status_code=r.status_code)

    data["stream_options"] = {**(data.get("stream_options") or {}), "include_usage": True}

    async def relay() -> AsyncIterator[bytes]:
        await gate.acquire(client.priority)
        tail = b""
        try:
            async with client_http() as http, http.stream("POST", f"{LLM_URL}/v1/chat/completions", json=data) as r:
                async for chunk in r.aiter_raw():
                    tail = (tail + chunk)[-4096:]
                    yield chunk
        finally:
            gate.release()
            record(client, *sse_usage(tail))

    return StreamingResponse(relay(), media_type="text/event-stream")


@app.post("/v1/embeddings")
async def embeddings(data: dict[str, Any] = Depends(body), client: Client = Depends(authorised)) -> dict[str, Any]:
    texts = data.get("input")
    texts = [texts] if isinstance(texts, str) else texts
    if not isinstance(texts, list) or not texts or len(texts) > MAX_TEXTS or not all(isinstance(t, str) for t in texts):
        raise HTTPException(400, f"input must be a string or 1..{MAX_TEXTS} strings")
    check_quota(client)
    async with client_http() as http:
        r = await http.post(f"{EMBED_URL}/embed", json={"texts": texts})
    if r.status_code != 200:
        raise HTTPException(502, "embedder failed")
    vectors = r.json()["embeddings"]
    tokens = sum(len(t.split()) for t in texts)  # a word count stands in for the tokenizer: close enough for a quota
    record(client, tokens, 0)
    return {
        "object": "list",
        "model": EMBED_MODEL,
        "data": [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vectors)],
        "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
    }
