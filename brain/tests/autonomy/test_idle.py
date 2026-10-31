# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 14.5 idle policy - the five steps, in order (T-086)."""

from __future__ import annotations

import pytest

from neml_brain.autonomy.idle import IDLE_SLEEP_S, IdleAction, IdleDeps, idle_policy


class Spy:
    """All five steps available; flip one off at a time to walk down the order."""

    def __init__(self, **off):
        self.calls: list[str] = []
        self.charged: list[str] = []
        self.slept: list[float] = []
        self.off = off

    def _on(self, name: str) -> bool:
        return not self.off.get(name, False)

    async def robot_batteries(self):
        self.calls.append("battery")
        return {"R01": 0.20, "R02": 0.90} if self._on("battery") else {"R01": 0.31}

    async def send_to_charger(self, robot_id: str) -> None:
        self.charged.append(robot_id)

    async def budget_ok(self) -> bool:
        self.calls.append("budget")
        return self._on("budget")

    async def make_exploration_task(self) -> bool:
        self.calls.append("exploration")
        return self._on("exploration")

    async def make_calibration_task(self) -> bool:
        self.calls.append("calibration")
        return self._on("calibration")

    async def consolidate_memory(self) -> int:
        self.calls.append("memory")
        return 12 if self._on("memory") else 0

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)

    def deps(self) -> IdleDeps:
        return IdleDeps(
            robot_batteries=self.robot_batteries,
            send_to_charger=self.send_to_charger,
            make_exploration_task=self.make_exploration_task,
            make_calibration_task=self.make_calibration_task,
            consolidate_memory=self.consolidate_memory,
            budget_ok=self.budget_ok,
        )


async def _run(spy: Spy) -> IdleAction:
    return await idle_policy(spy.deps(), sleep=spy.sleep)


async def test_step1_low_battery_wins_over_everything():
    spy = Spy()
    assert await _run(spy) == IdleAction.CHARGING
    assert spy.charged == ["R01"]  # R02 is at 90 %, left alone
    assert spy.calls == ["battery"]  # nothing further is even asked


async def test_step2_exploration_when_battery_is_fine():
    spy = Spy(battery=True)
    assert await _run(spy) == IdleAction.EXPLORATION
    assert spy.calls == ["battery", "budget", "exploration"]


async def test_step3_calibration_when_there_is_no_coverage_gap():
    spy = Spy(battery=True, exploration=True)
    assert await _run(spy) == IdleAction.CALIBRATION
    assert spy.calls == ["battery", "budget", "exploration", "calibration"]


async def test_step5_memory_consolidation_is_the_last_real_work():
    spy = Spy(battery=True, exploration=True, calibration=True)
    assert await _run(spy) == IdleAction.MEMORY
    assert spy.calls[-1] == "memory"
    assert spy.slept == []


async def test_step6_sixty_second_sleep_when_nothing_is_left():
    spy = Spy(battery=True, exploration=True, calibration=True, memory=True)
    assert await _run(spy) == IdleAction.SLEPT
    assert spy.slept == [IDLE_SLEEP_S]
    assert IDLE_SLEEP_S == 60


async def test_never_exceeds_budget():
    """SPEC 14.5: the gap is filled with cheap work, never outside the budget."""
    spy = Spy(battery=True, budget=True)
    assert await _run(spy) == IdleAction.SLEPT
    assert spy.calls == ["battery", "budget"]
    assert spy.slept == [IDLE_SLEEP_S]


async def test_charging_is_not_gated_on_the_budget():
    """A robot below 30 % is sent to charge whatever the budget says."""
    spy = Spy(budget=True)
    assert await _run(spy) == IdleAction.CHARGING
    assert spy.charged == ["R01"]


@pytest.mark.parametrize("soc", [0.0, 0.299])
async def test_battery_threshold_is_thirty_percent(soc):
    spy = Spy(battery=True)

    async def batteries():
        spy.calls.append("battery")
        return {"R01": soc}

    deps = spy.deps()
    deps.robot_batteries = batteries
    assert await idle_policy(deps, sleep=spy.sleep) == IdleAction.CHARGING
