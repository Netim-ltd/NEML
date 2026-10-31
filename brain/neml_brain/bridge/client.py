# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Outbound-only cloud bridge (SPEC 3.1 + 9.5).

The lab sits behind NAT: the remote server NEVER connects inbound. This client
dials NEML_CLOUD_WS over WSS, keeps the socket open, drains the outbox in seq
order and applies server->lab messages exactly once per idempotency_key.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

import structlog
from websockets.asyncio.client import connect as ws_connect

from .outbox import Outbox
from .protocol import (
    SERVER_TYPES,
    Envelope,
    LabMessageType,
    new_envelope,
)

BACKOFF_START_S = 1.0
BACKOFF_MAX_S = 60.0  # SPEC 3.1: 1s -> 2s -> 4s ... max 60s
HEARTBEAT_S = 15.0  # SPEC 9.5
SILENCE_TIMEOUT_S = 45.0  # SPEC 9.5: unanswered for 45 s -> link is down
DRAIN_BATCH = 100
DRAIN_POLL_S = 1.0

log = structlog.get_logger(__name__)


def backoff_delays() -> Iterator[float]:
    """1, 2, 4, 8, 16, 32, 60, 60, ... (SPEC 3.1)."""
    delay = BACKOFF_START_S
    while True:
        yield delay
        delay = min(delay * 2, BACKOFF_MAX_S)


class CloudBridge:
    """Persistent outbound WSS link to the remote API."""

    def __init__(
        self,
        url: str,
        node_id: str,
        api_key: str,
        outbox: Outbox,
        *,
        on_message: Callable[[Envelope], Awaitable[None]],
        on_status: Callable[[bool], Awaitable[None]] | None = None,
        connect: Callable[..., Any] = ws_connect,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.url = url
        self.node_id = node_id
        self.api_key = api_key
        self.outbox = outbox
        self.online = False
        self._on_message = on_message
        self._on_status = on_status
        self._connect = connect
        self._sleep = sleep
        self._wake = asyncio.Event()
        self._inflight: set[asyncio.Task[None]] = set()
        self._slots = asyncio.Semaphore(4)  # commands worked on at the same time

    # --- public ---------------------------------------------------------
    def send(
        self,
        message_type: LabMessageType,
        payload: dict[str, Any] | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> Envelope:
        """Queue a lab->server message. Works offline; drains on reconnect."""
        env = new_envelope(
            self.outbox.next_seq(), message_type, payload, idempotency_key=idempotency_key
        )
        self.outbox.put(env)
        self._wake.set()
        return env

    async def run(self, *, stop: asyncio.Event | None = None) -> None:
        """Connect-forever loop. Only cancellation gets out of here."""
        delays = backoff_delays()
        while stop is None or not stop.is_set():
            try:
                if await self._session():
                    delays = backoff_delays()  # a real connection resets the backoff
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - the link may fail any way it likes
                log.warning("bridge.session_failed", error=str(exc))
            finally:
                await self._set_online(False)
            await self._sleep(next(delays))

    # --- session --------------------------------------------------------
    async def _session(self) -> bool:
        async with self._connect(
            self.url,
            additional_headers={"X-NEML-Key": self.api_key, "X-NEML-Node": self.node_id},
            compression="deflate",  # SPEC 9.5: permessage-deflate
            ping_interval=None,  # heartbeat is ours, on the spec'd timings
        ) as ws:
            await self._set_online(True)
            tasks = [
                asyncio.create_task(self._drain(ws)),
                asyncio.create_task(self._receive(ws)),
                asyncio.create_task(self._heartbeat(ws)),
            ]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                task.result()  # re-raise whatever killed the session
        return True

    async def _drain(self, ws: Any) -> None:
        while True:
            batch = self.outbox.peek(DRAIN_BATCH)
            for env in batch:
                await ws.send(env.model_dump_json())
                self.outbox.ack(env.seq)
            if not batch:
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), DRAIN_POLL_S)
                except TimeoutError:
                    pass

    async def _receive(self, ws: Any) -> None:
        async for raw in ws:
            env = Envelope.model_validate_json(raw)
            if env.type not in SERVER_TYPES:
                log.warning("bridge.unexpected_type", type=env.type, seq=env.seq)
                continue
            if env.type == "ping":
                continue
            if not self.outbox.claim(env.idempotency_key):
                log.info("bridge.duplicate_ignored", key=env.idempotency_key, seq=env.seq)
                continue
            # A command can wait minutes for the language model; reading must go on meanwhile, and a
            # dropped session must not cancel the work (its ack waits in the outbox).
            task = asyncio.create_task(self._handle(env))
            self._inflight.add(task)
            task.add_done_callback(self._inflight.discard)

    async def _handle(self, env: Envelope) -> None:
        async with self._slots:
            try:
                await self._on_message(env)
            except Exception as exc:  # noqa: BLE001 - one bad message must not end the session
                log.error("bridge.handler_failed", type=env.type, error=str(exc)[:200])

    async def _heartbeat(self, ws: Any) -> None:
        """15 s heartbeat; 45 s without an answer means the link is dead."""
        while True:
            await asyncio.sleep(HEARTBEAT_S)
            pong = await ws.ping()
            await asyncio.wait_for(pong, SILENCE_TIMEOUT_S)

    async def _set_online(self, online: bool) -> None:
        if online == self.online:
            return
        self.online = online
        # No `state` envelope here: the cloud's `state` type is a per-robot mirror
        # (RobotStatePayload) and it already knows the link is up or down from the
        # socket itself. Sending {node_id, online} made it parse a robot with no id.
        if self._on_status is not None:
            await self._on_status(online)
        log.info("bridge.status", online=online)


__all__ = ["CloudBridge", "backoff_delays"]
