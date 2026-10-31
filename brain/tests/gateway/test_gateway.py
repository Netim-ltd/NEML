# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from neml_brain import gateway

BIG, SMALL = "b" * 24, "s" * 24


@pytest.fixture
def web(monkeypatch, tmp_path):
    monkeypatch.setenv("NEML_GATEWAY_DIR", str(tmp_path))
    monkeypatch.delenv("NEML_GATEWAY_CLIENTS", raising=False)
    monkeypatch.delenv("NEML_GATEWAY_KEYS", raising=False)
    (tmp_path / "clients.json").write_text(
        json.dumps({"clients": [
            {"name": "neml", "key": BIG, "max_tokens": 8192, "daily_tokens": 0, "priority": 0},
            {"name": "customer", "key": SMALL, "max_tokens": 100, "daily_tokens": 50, "priority": 5},
        ]}),
        encoding="utf-8",
    )
    gateway._cache.update(stamp=None, clients=[])
    seen = {}

    def upstream(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/embed":
            return httpx.Response(200, json={"embeddings": [[0.1, 0.2], [0.3, 0.4]]})
        seen["chat"] = json.loads(request.read())
        return httpx.Response(200, json={"choices": [{"message": {"content": "merhaba"}}], "usage": {"prompt_tokens": 20, "completion_tokens": 40}})

    monkeypatch.setattr(gateway, "client_http", lambda: httpx.AsyncClient(transport=httpx.MockTransport(upstream)))
    return TestClient(gateway.app), seen


def auth(key):
    return {"Authorization": f"Bearer {key}"}


def ask(client, key, **extra):
    return client.post("/v1/chat/completions", headers=auth(key), json={"messages": [{"role": "user", "content": "selam"}], **extra})


def test_unknown_keys_are_refused_and_plain_env_keys_work_without_a_clients_file(web, monkeypatch, tmp_path):
    client, _ = web
    assert client.get("/v1/models").status_code == 401
    assert client.get("/v1/models", headers=auth("x" * 24)).status_code == 401
    assert client.get("/v1/models", headers=auth(BIG)).status_code == 200
    (tmp_path / "clients.json").unlink()
    monkeypatch.setenv("NEML_GATEWAY_KEYS", f"{SMALL},short")  # a key under 16 characters does not count
    assert client.get("/v1/models", headers=auth(SMALL)).status_code == 200 and client.get("/v1/models", headers=auth("short")).status_code == 401


def test_each_client_has_its_own_token_cap(web):
    client, seen = web
    ask(client, BIG, max_tokens=999999, model="gpt-4")
    assert seen["chat"]["max_tokens"] == 8192 and "model" not in seen["chat"]
    ask(client, SMALL, max_tokens=5000)
    assert seen["chat"]["max_tokens"] == 100
    ask(client, SMALL)  # nothing asked: the default, cut to the client's maximum
    assert seen["chat"]["max_tokens"] == 100
    assert client.post("/v1/chat/completions", headers=auth(BIG), json={"messages": []}).status_code == 400


def test_daily_quota_counts_real_usage_and_then_refuses(web):
    client, _ = web
    assert ask(client, SMALL).status_code == 200  # 60 tokens used of 50: the next one is over
    r = ask(client, SMALL)
    assert r.status_code == 429 and "quota" in r.json()["detail"]
    assert ask(client, BIG).status_code == 200  # unlimited client unaffected
    u = client.get("/v1/usage", headers=auth(SMALL)).json()
    assert u["max_tokens"] == 100 and u["today"]["total"] == 60 and u["today"]["requests"] == 1


def test_limits_change_without_a_restart(web, tmp_path):
    client, seen = web
    ask(client, SMALL)
    assert seen["chat"]["max_tokens"] == 100
    path = tmp_path / "clients.json"
    path.write_text(json.dumps({"clients": [{"name": "customer", "key": SMALL, "max_tokens": 777}]}), encoding="utf-8")
    import os
    os.utime(path, ns=(10**18, 10**18))  # a new modification time, as an edit would give
    ask(client, SMALL)
    assert seen["chat"]["max_tokens"] == 777


def test_embeddings_follow_the_openai_shape_and_check_the_input(web):
    client, _ = web
    r = client.post("/v1/embeddings", headers=auth(BIG), json={"input": ["a b", "c"]})
    assert [d["index"] for d in r.json()["data"]] == [0, 1] and r.json()["data"][1]["embedding"] == [0.3, 0.4]
    assert client.post("/v1/embeddings", headers=auth(BIG), json={"input": []}).status_code == 400
    assert client.post("/v1/embeddings", headers=auth(BIG), json={"input": [1]}).status_code == 400


def test_stream_usage_is_read_from_the_last_event():
    tail = b'data: {"choices":[]}\n\ndata: {"choices":[],"usage":{"prompt_tokens":7,"completion_tokens":9}}\n\ndata: [DONE]\n\n'
    assert gateway.sse_usage(tail) == (7, 9) and gateway.sse_usage(b"data: [DONE]") == (0, 0)


def test_the_waiting_client_with_the_lower_priority_number_goes_first():
    async def scenario():
        g = gateway.Gate()
        order = []
        await g.acquire(0)  # the model is busy

        async def waiter(name, priority):
            await g.acquire(priority)
            order.append(name)
            g.release()

        tasks = [asyncio.create_task(waiter("customer", 5)), asyncio.create_task(waiter("neml", 0))]
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        g.release()
        await asyncio.gather(*tasks)
        return order

    assert asyncio.run(scenario()) == ["neml", "customer"]


def test_the_client_tool_creates_updates_and_never_lists_keys(tmp_path, monkeypatch, capsys):
    from neml_brain import gateway_clients as gc

    monkeypatch.setenv("NEML_GATEWAY_DIR", str(tmp_path))
    monkeypatch.delenv("NEML_GATEWAY_CLIENTS", raising=False)
    gc.main(["set", "customer-a", "--max-tokens", "512", "--daily", "1000", "--priority", "5"])
    out = capsys.readouterr().out
    key = out.split("shown once):")[1].strip()
    assert len(key) >= 24
    gc.main(["set", "customer-a", "--max-tokens", "900"])  # only what is given changes, the key stays
    assert "key (shown once)" not in capsys.readouterr().out
    row = gc.load()[0]
    assert row["key"] == key and row["max_tokens"] == 900 and row["daily_tokens"] == 1000 and row["priority"] == 5
    gc.main(["list"])
    assert key not in capsys.readouterr().out
    gc.main(["remove", "customer-a"])
    assert gc.load() == []


def test_the_lab_operation_validates_lists_without_keys_and_shows_a_new_key_once(tmp_path, monkeypatch):
    from neml_brain import gateway_clients as gc

    monkeypatch.setenv("NEML_GATEWAY_DIR", str(tmp_path))
    monkeypatch.delenv("NEML_GATEWAY_CLIENTS", raising=False)
    made = gc.operate({"action": "set", "name": "musteri-a", "maxTokens": 512, "dailyTokens": 1000, "priority": 5})
    assert made["new_key"]["name"] == "musteri-a" and len(made["new_key"]["key"]) >= 24
    again = gc.operate({"action": "list"})
    assert again["new_key"] is None and "key" not in again["clients"][0] and again["clients"][0]["key_hint"].startswith("…")
    assert gc.operate({"action": "set", "name": "musteri-a", "maxTokens": 900})["clients"][0]["max_tokens"] == 900
    assert gc.operate({"action": "rotate", "name": "musteri-a"})["new_key"]["key"] != made["new_key"]["key"]
    for bad in ({"action": "set", "name": "Büyük Ad"}, {"action": "set", "name": "ok-ad", "maxTokens": 999999}, {"action": "set", "name": "ok-ad", "priority": "1"}, {"action": "zzz", "name": "ok-ad"}):
        with pytest.raises(ValueError):
            gc.operate(bad)
    assert gc.operate({"action": "remove", "name": "musteri-a"})["clients"] == []
