# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 3.1/9.5 bridge client. Websocket double throughout - no network."""

from __future__ import annotations

import asyncio
from itertools import islice

import pytest

from neml_brain.bridge import client as client_module
from neml_brain.bridge.client import BACKOFF_MAX_S, CloudBridge, backoff_delays
from neml_brain.bridge.outbox import Outbox
from neml_brain.bridge.protocol import Envelope, new_envelope

EXPECTED_BACKOFF = [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0]


class FakeWS:
    """Websocket double: collects sends, replays inbound, gates the reader."""

    def __init__(
        self,
        inbound: list[Envelope] | None = None,
        release_after_sends: int = 0,
        hang: bool = False,
    ):
        self.sent: list[str] = []
        self.inbound = inbound or []
        self.pings = 0
        self.hang = hang  # a peer that accepts frames but never answers
        self._release = asyncio.Event()
        self._release_after = release_after_sends
        if release_after_sends == 0:
            self._release.set()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send(self, raw: str) -> None:
        self.sent.append(raw)
        if len(self.sent) >= self._release_after:
            self._release.set()

    async def ping(self):
        self.pings += 1
        return asyncio.get_running_loop().create_future()

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        await self._release.wait()
        for env in self.inbound:
            yield env.model_dump_json()
        if self.hang:
            await asyncio.Event().wait()  # the socket stays open and silent


def _bridge(tmp_path, connect, sleep, on_message=None, on_status=None) -> CloudBridge:
    async def _noop(_env):
        return None

    return CloudBridge(
        "wss://api.example.test/bridge/ws",
        "lab-01",
        "key",
        Outbox(tmp_path / "outbox.db"),
        on_message=on_message or _noop,
        on_status=on_status,
        connect=connect,
        sleep=sleep,
    )


def test_backoff_generator_matches_spec():
    assert list(islice(backoff_delays(), 8)) == EXPECTED_BACKOFF
    assert max(islice(backoff_delays(), 50)) == BACKOFF_MAX_S


async def test_reconnect_backoff_sequence(tmp_path):
    """SPEC 3.1: 1s, 2s, 4s ... capped at 60s, applied by the run loop."""
    delays: list[float] = []
    stop = asyncio.Event()

    async def fake_sleep(d: float) -> None:
        delays.append(d)
        if len(delays) >= len(EXPECTED_BACKOFF):
            stop.set()

    def refuse(*_a, **_kw):
        raise OSError("connection refused")

    await _bridge(tmp_path, refuse, fake_sleep).run(stop=stop)
    assert delays == EXPECTED_BACKOFF


async def test_backoff_resets_after_a_successful_session(tmp_path):
    delays: list[float] = []
    stop = asyncio.Event()
    attempts = {"n": 0}

    async def fake_sleep(d: float) -> None:
        delays.append(d)
        if len(delays) >= 5:
            stop.set()

    def connect(*_a, **_kw):
        attempts["n"] += 1
        if attempts["n"] == 3:  # third attempt connects, then the peer hangs up
            return FakeWS()
        raise OSError("connection refused")

    await _bridge(tmp_path, connect, fake_sleep).run(stop=stop)
    # 1, 2 while failing; the live session resets it; 1, 2, 4 after
    assert delays == [1.0, 2.0, 1.0, 2.0, 4.0]


async def test_queued_messages_drain_in_seq_order(tmp_path):
    stop = asyncio.Event()
    ws = FakeWS(release_after_sends=3)  # the 3 queued messages

    async def fake_sleep(_d: float) -> None:
        stop.set()

    bridge = _bridge(tmp_path, lambda *_a, **_kw: ws, fake_sleep)
    queued = [bridge.send("telemetry", {"n": i}) for i in range(3)]
    await bridge.run(stop=stop)

    sent = [Envelope.model_validate_json(raw) for raw in ws.sent]
    assert [e.seq for e in sent[:3]] == [e.seq for e in queued]
    assert len(sent) == 3  # no `state` envelope: the cloud sees the link itself
    assert bridge.outbox.pending() == 0


async def test_duplicate_idempotency_key_applies_once(tmp_path):
    stop = asyncio.Event()
    env = new_envelope(1, "command", {"command_id": "c1", "kind": "estop", "args": {}})
    replay = Envelope.model_validate_json(env.model_dump_json())
    ws = FakeWS(inbound=[env, replay, env])
    applied: list[str] = []

    async def on_message(e: Envelope) -> None:
        applied.append(e.payload["command_id"])

    async def fake_sleep(_d: float) -> None:
        stop.set()

    bridge = _bridge(tmp_path, lambda *_a, **_kw: ws, fake_sleep, on_message=on_message)
    await bridge.run(stop=stop)
    assert applied == ["c1"]


async def test_ping_is_liveness_only_and_lab_types_are_rejected(tmp_path):
    stop = asyncio.Event()
    inbound = [
        new_envelope(1, "ping"),
        new_envelope(2, "telemetry", {"bogus": True}),  # server must never send this
    ]
    ws = FakeWS(inbound=inbound)
    applied: list[Envelope] = []

    async def on_message(e: Envelope) -> None:
        applied.append(e)

    async def fake_sleep(_d: float) -> None:
        stop.set()

    bridge = _bridge(tmp_path, lambda *_a, **_kw: ws, fake_sleep, on_message=on_message)
    await bridge.run(stop=stop)
    assert applied == []


async def test_offline_status_is_published_when_the_link_drops(tmp_path):
    stop = asyncio.Event()
    statuses: list[bool] = []

    async def on_status(online: bool) -> None:
        statuses.append(online)

    async def fake_sleep(_d: float) -> None:
        stop.set()

    bridge = _bridge(tmp_path, lambda *_a, **_kw: FakeWS(), fake_sleep, on_status=on_status)
    await bridge.run(stop=stop)
    assert statuses == [True, False]  # SPEC 9.5 BrainStatus{online:false}
    assert bridge.online is False
    assert bridge.outbox.pending() == 0  # going offline queues nothing (cloud detects it)


async def test_offline_send_never_raises(tmp_path):
    """SPEC 3.1: the lab works fully offline; telemetry just piles up locally."""
    bridge = _bridge(tmp_path, lambda *_a, **_kw: FakeWS(), asyncio.sleep)
    for i in range(10):
        bridge.send("telemetry", {"n": i})
    assert bridge.outbox.pending() == 10
    assert bridge.online is False


async def test_compression_and_credentials_are_on_the_dial(tmp_path):
    seen: dict = {}
    stop = asyncio.Event()

    def connect(url, **kw):
        seen.update(kw, url=url)
        return FakeWS()

    async def fake_sleep(_d: float) -> None:
        stop.set()

    await _bridge(tmp_path, connect, fake_sleep).run(stop=stop)
    assert seen["compression"] == "deflate"  # SPEC 9.5 permessage-deflate
    assert seen["additional_headers"]["X-NEML-Key"] == "key"
    assert seen["additional_headers"]["X-NEML-Node"] == "lab-01"
    assert seen["url"].startswith("wss://")


async def test_heartbeat_timeout_drops_a_silent_peer(tmp_path, monkeypatch):
    """SPEC 9.5: heartbeat every 15 s; 45 s unanswered means the link is down.

    The timings are scaled down here - the behaviour under test is that an
    unanswered heartbeat ends the session and flips BrainStatus to offline.
    """
    monkeypatch.setattr(client_module, "HEARTBEAT_S", 0.01)
    monkeypatch.setattr(client_module, "SILENCE_TIMEOUT_S", 0.02)
    stop = asyncio.Event()
    ws = FakeWS(hang=True)  # accepts the ping, never returns a pong
    statuses: list[bool] = []

    async def on_status(online: bool) -> None:
        statuses.append(online)

    async def fake_sleep(_d: float) -> None:
        stop.set()

    bridge = _bridge(tmp_path, lambda *_a, **_kw: ws, fake_sleep, on_status=on_status)
    await asyncio.wait_for(bridge.run(stop=stop), timeout=5)
    assert ws.pings >= 1
    assert statuses == [True, False]
    assert bridge.online is False


async def test_heartbeat_ratio_is_the_spec_one(tmp_path):
    assert client_module.HEARTBEAT_S == 15.0
    assert client_module.SILENCE_TIMEOUT_S == 45.0


@pytest.mark.parametrize("failure", [OSError("dns"), RuntimeError("tls")])
async def test_run_survives_any_connect_failure(tmp_path, failure):
    stop = asyncio.Event()
    n = {"c": 0}

    async def fake_sleep(_d: float) -> None:
        n["c"] += 1
        if n["c"] >= 3:
            stop.set()

    def boom(*_a, **_kw):
        raise failure

    await _bridge(tmp_path, boom, fake_sleep).run(stop=stop)
    assert n["c"] == 3
