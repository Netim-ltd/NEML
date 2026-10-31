# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 4.5 GPU mutex. No Docker here: the httpx transport is the double."""

from __future__ import annotations

import asyncio
import socket

import httpx
import pytest
from prometheus_client import REGISTRY

from neml_brain.runtime.gpu_lock import DockerClient, GpuLock, GpuLockTimeout
from neml_brain.services import Gpu


class FakeDocker:
    """Records the Docker Engine calls the real client would make."""

    def __init__(self, status: int = 204) -> None:
        self.calls: list[str] = []
        self.status = status
        self.client = DockerClient(transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request.url.path)
        return httpx.Response(self.status)


@pytest.fixture
def docker() -> FakeDocker:
    return FakeDocker()


@pytest.mark.parametrize("profile", ["fast", "lidar"])
async def test_cpu_profiles_leave_vllm_running(docker: FakeDocker, profile: str) -> None:
    lock = GpuLock(docker.client)
    await lock.acquire("sim", profile=profile)
    await lock.release("sim")
    assert docker.calls == []


async def test_visual_profile_stops_then_restarts_vllm(docker: FakeDocker) -> None:
    lock = GpuLock(docker.client)
    await lock.acquire("sim", profile="visual")
    assert docker.calls == ["/containers/neml-vllm/stop"]
    await lock.release("sim")
    assert docker.calls == ["/containers/neml-vllm/stop", "/containers/neml-vllm/start"]


async def test_manual_gpu_facade_stops_vllm_and_reports_wait(docker: FakeDocker) -> None:
    gpu = Gpu(GpuLock(docker.client))
    waited = await gpu.acquire("operator")
    assert waited >= 0.0
    assert docker.calls == ["/containers/neml-vllm/stop"]
    assert await gpu.release("operator") is True
    assert await gpu.release("operator") is False
    assert docker.calls[-1] == "/containers/neml-vllm/start"


async def test_reentrant_acquire_does_not_deadlock(docker: FakeDocker) -> None:
    lock = GpuLock(docker.client)
    await lock.acquire("sim", profile="visual")
    await asyncio.wait_for(lock.acquire("sim", profile="visual"), 1.0)
    await lock.release("sim")
    assert docker.calls == ["/containers/neml-vllm/stop"], "vLLM stays down while still held"
    await lock.release("sim")
    assert docker.calls[-1] == "/containers/neml-vllm/start"


async def test_second_consumer_waits_then_gets_it(docker: FakeDocker) -> None:
    lock = GpuLock(docker.client)
    await lock.acquire("sim")
    waiter = asyncio.create_task(lock.acquire("llm", timeout_s=5))
    await asyncio.sleep(0.01)
    assert not waiter.done(), "single GPU consumer guarantee"
    await lock.release("sim")
    await asyncio.wait_for(waiter, 1.0)
    await lock.release("llm")


async def test_timeout_raises(docker: FakeDocker) -> None:
    lock = GpuLock(docker.client)
    await lock.acquire("sim")
    with pytest.raises(GpuLockTimeout):
        await lock.acquire("llm", timeout_s=0.02)
    await lock.release("sim")


async def test_wait_metric_is_emitted(docker: FakeDocker) -> None:
    before = (
        REGISTRY.get_sample_value("neml_gpu_lock_wait_seconds_count", {"consumer": "metric-probe"})
        or 0.0
    )
    lock = GpuLock(docker.client)
    await lock.acquire("metric-probe")
    await lock.release("metric-probe")
    after = REGISTRY.get_sample_value(
        "neml_gpu_lock_wait_seconds_count", {"consumer": "metric-probe"}
    )
    assert after == before + 1


async def test_docker_failure_does_not_strand_the_lock() -> None:
    broken = FakeDocker(status=500)
    lock = GpuLock(broken.client)
    with pytest.raises(httpx.HTTPStatusError):
        await lock.acquire("sim", profile="visual")
    await asyncio.wait_for(lock.acquire("other"), 1.0)  # lock was released again
    await lock.release("other")


async def test_release_by_a_non_holder_is_rejected(docker: FakeDocker) -> None:
    lock = GpuLock(docker.client)
    await lock.acquire("sim")
    with pytest.raises(RuntimeError):
        await lock.release("llm")
    await lock.release("sim")


@pytest.mark.integration
@pytest.mark.skipif(
    not hasattr(socket, "AF_UNIX"), reason="the docker socket is a POSIX unix socket"
)
async def test_real_docker_socket() -> None:
    """Needs a live Docker daemon and the neml-vllm container."""
    lock = GpuLock()
    await lock.acquire("integration", profile="visual")
    await lock.release("integration")


def test_spec_signature_is_intact() -> None:
    import inspect

    sig = inspect.signature(GpuLock.acquire)
    assert list(sig.parameters) == ["self", "consumer", "timeout_s", "profile"]
    assert sig.parameters["timeout_s"].default == 300
    assert list(inspect.signature(GpuLock.release).parameters) == ["self", "consumer"]
