# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 4.5 GPU mutex.

3 GB cannot hold vLLM and a rendering Gazebo at the same time. Only the
`visual` sim profile needs the GPU, so only `visual` stops the neml-vllm
container; `fast` and `lidar` render on CPU and leave vLLM running.

Docker is driven over its UNIX socket with httpx (SPEC 8.1 lists httpx; the
docker SDK is not a listed dependency, SPEC 1.3 keeps tools out of the tree).
"""

from __future__ import annotations

import asyncio
import time

import httpx

from neml_brain.api.metrics import GPU_LOCK_WAIT  # SPEC 18.3, declared once

VLLM_CONTAINER = "neml-vllm"
DOCKER_SOCKET = "/var/run/docker.sock"
GPU_PROFILES = frozenset({"visual"})  # SPEC 4.5 table: only `visual` needs the GPU
RESTART_BUDGET_S = 40.0  # SPEC 4.5: vLLM needs ~40 s to come back; planned cost


class GpuLockTimeout(TimeoutError):
    pass


class DockerClient:
    """The two Docker Engine calls this module needs."""

    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        socket_path: str = DOCKER_SOCKET,
    ) -> None:
        self._client = httpx.AsyncClient(
            transport=transport or httpx.AsyncHTTPTransport(uds=socket_path),
            base_url="http://docker",
            timeout=RESTART_BUDGET_S + 20.0,
        )

    async def stop(self, container: str) -> None:
        await self._call(f"/containers/{container}/stop")

    async def start(self, container: str) -> None:
        await self._call(f"/containers/{container}/start")

    async def _call(self, path: str) -> None:
        response = await self._client.post(path)
        if response.status_code == 304:  # already in the requested state
            return
        response.raise_for_status()

    async def aclose(self) -> None:
        await self._client.aclose()


class GpuLock:
    """Tek GPU tuketicisi garantisi. Docker socket ile vLLM durdurulur."""

    def __init__(
        self, docker: DockerClient | None = None, *, container: str = VLLM_CONTAINER
    ) -> None:
        self._docker = docker if docker is not None else DockerClient()
        self._container = container
        # ponytail: in-process asyncio lock. Ceiling: one neml-brain process owns the GPU.
        # Upgrade path: a PostgreSQL advisory lock if the brain ever runs multi-process.
        self._lock = asyncio.Lock()
        self._owner: str | None = None
        self._depth = 0
        self._vllm_stopped = False

    async def acquire(
        self, consumer: str, timeout_s: float = 300, *, profile: str = "fast"
    ) -> float:
        if self._owner == consumer:  # re-entrant: same consumer never waits on itself
            await self._apply_profile(profile)  # first, so a failure leaves depth balanced
            self._depth += 1
            return 0.0

        started = time.monotonic()
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout_s)
        except TimeoutError as exc:
            GPU_LOCK_WAIT.labels(consumer).observe(time.monotonic() - started)
            raise GpuLockTimeout(
                f"{consumer} waited {timeout_s}s for the GPU, holder is {self._owner}"
            ) from exc
        waited_s = time.monotonic() - started
        GPU_LOCK_WAIT.labels(consumer).observe(waited_s)
        self._owner = consumer
        self._depth = 1
        try:
            await self._apply_profile(profile)
        except Exception:
            self._owner = None
            self._depth = 0
            self._lock.release()
            raise
        return waited_s

    async def release(self, consumer: str) -> bool:
        if self._owner != consumer:
            raise RuntimeError(f"{consumer} does not hold the GPU lock ({self._owner} does)")
        self._depth -= 1
        if self._depth > 0:
            return True
        self._owner = None
        try:
            if self._vllm_stopped:
                self._vllm_stopped = False
                await self._docker.start(self._container)
        finally:
            self._lock.release()
        return True

    async def _apply_profile(self, profile: str) -> None:
        if profile in GPU_PROFILES and not self._vllm_stopped:
            await self._docker.stop(self._container)
            self._vllm_stopped = True
