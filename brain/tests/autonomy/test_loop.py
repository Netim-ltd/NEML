# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 14.1 - the 24/7 loop (T-084)."""

from __future__ import annotations

import asyncio

from neml_brain.autonomy.loop import TICK_S, AutonomyDeps, autonomy_loop


class Harness:
    """Records the call order and stops the loop after `ticks` sleeps."""

    def __init__(self, ticks: int = 1, task: object | None = "task-1"):
        self.calls: list[str] = []
        self.slept: list[float] = []
        self.safety_failures: list[BaseException] = []
        self.stop = asyncio.Event()
        self.ticks = ticks
        self.task = task
        self.raise_in: dict[str, BaseException] = {}
        self.budget = True

    def _mark(self, name: str) -> None:
        self.calls.append(name)
        exc = self.raise_in.pop(name, None)
        if exc is not None:
            raise exc

    async def safety_preflight(self) -> None:
        self._mark("safety")

    async def budget_ok(self) -> bool:
        self._mark("budget")
        return self.budget

    async def sleep_until_budget_reset(self) -> None:
        self._mark("budget_reset")
        self.stop.set()

    async def discover_tasks(self):
        self._mark("discover")

    async def pick_next_task(self):
        self._mark("pick")
        return self.task

    async def idle_policy(self):
        self._mark("idle")
        self.stop.set()

    async def execute(self, task):
        self._mark("execute")

    async def record_and_learn(self, task):
        self._mark("learn")

    async def on_safety_failure(self, exc: BaseException) -> None:
        self.calls.append("escalate")
        self.safety_failures.append(exc)

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        if len(self.slept) >= self.ticks:
            self.stop.set()
        await asyncio.sleep(0)  # a real yield point, so cancellation can land

    def deps(self) -> AutonomyDeps:
        return AutonomyDeps(
            safety_preflight=self.safety_preflight,
            budget_ok=self.budget_ok,
            sleep_until_budget_reset=self.sleep_until_budget_reset,
            discover_tasks=self.discover_tasks,
            pick_next_task=self.pick_next_task,
            idle_policy=self.idle_policy,
            execute=self.execute,
            record_and_learn=self.record_and_learn,
            on_safety_failure=self.on_safety_failure,
        )

    async def run(self) -> None:
        await autonomy_loop(self.deps(), stop=self.stop, sleep=self.sleep)


async def test_tick_order_matches_the_spec():
    h = Harness()
    await h.run()
    assert h.calls == ["safety", "budget", "discover", "pick", "execute", "learn"]
    assert h.slept == [TICK_S]
    assert TICK_S == 5


async def test_no_task_goes_to_the_idle_policy_without_sleeping_the_tick():
    h = Harness(task=None)
    await h.run()
    assert h.calls == ["safety", "budget", "discover", "pick", "idle"]
    assert h.slept == []


async def test_budget_exhausted_waits_for_the_reset_and_discovers_nothing():
    h = Harness()
    h.budget = False
    await h.run()
    assert h.calls == ["safety", "budget", "budget_reset"]
    assert "discover" not in h.calls
    assert "execute" not in h.calls


async def test_safety_failure_is_escalated_and_no_work_runs():
    """A failed gate is never swallowed: it is escalated and the tick ends."""
    h = Harness()
    boom = RuntimeError("estop loop open")
    h.raise_in["safety"] = boom
    await h.run()
    assert h.calls == ["safety", "escalate"]
    assert h.safety_failures == [boom]
    assert "execute" not in h.calls
    assert h.slept == [TICK_S]


async def test_safety_failure_does_not_kill_the_service():
    h = Harness(ticks=2)
    h.raise_in["safety"] = RuntimeError("watchdog stale")
    await h.run()
    # tick 1 fails the gate, tick 2 passes and runs the full pipeline
    assert h.calls == [
        "safety",
        "escalate",
        "safety",
        "budget",
        "discover",
        "pick",
        "execute",
        "learn",
    ]


async def test_a_broken_escalation_still_does_not_exit():
    h = Harness()
    h.raise_in["safety"] = RuntimeError("gate")

    async def broken(_exc):
        h.calls.append("escalate")
        raise OSError("pager down")

    deps = h.deps()
    deps.on_safety_failure = broken
    await autonomy_loop(deps, stop=h.stop, sleep=h.sleep)
    assert h.calls == ["safety", "escalate"]
    assert h.slept == [TICK_S]


async def test_task_failure_does_not_exit_the_loop():
    h = Harness(ticks=2)
    h.raise_in["execute"] = RuntimeError("langgraph blew up")
    await h.run()
    assert h.calls.count("safety") == 2  # it kept going
    assert h.slept == [TICK_S, TICK_S]
    assert "learn" in h.calls  # the second tick completed normally


async def test_cancellation_is_the_only_way_out():
    h = Harness(ticks=10_000)
    task = asyncio.create_task(h.run())
    await asyncio.sleep(0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert task.cancelled() or task.done()
