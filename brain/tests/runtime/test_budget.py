# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""T-018 / SPEC 14.4 budget over the persisted budget_usage counters (ADR-011)."""

from __future__ import annotations

import datetime as dt
import os
from decimal import Decimal
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from prometheus_client import REGISTRY

from neml_brain.db import repo
from neml_brain.runtime.budget import Budget, BudgetExceeded

TRT = ZoneInfo("Europe/Istanbul")
SPEC_LIMITS = {
    "gpu_hours": 6.0,
    "sim_runs": 200.0,
    "robot_hours": 3.0,
    "filament_grams": 500.0,
    "pcb_orders": 1.0,
    "llm_tokens": 500000.0,
}


class Store:
    """The budget_usage rows, and the transaction the atomic upsert runs inside.

    The upsert charges before anyone can read it, so `rollback` is what makes a refused
    request cost nothing -- the double serves as both the table and the session.
    """

    def __init__(self) -> None:
        self.rows: dict[tuple[dt.date, str], Decimal] = {}
        self._staged: dict[tuple[dt.date, str], Decimal] = {}

    def _view(self) -> dict[tuple[dt.date, str], Decimal]:
        return {**self.rows, **self._staged}

    async def consume_budget(
        self, session: Any, *, resource: str, amount: Decimal, day: dt.date
    ) -> Decimal:
        total = self._view().get((day, resource), Decimal(0)) + amount
        self._staged[(day, resource)] = total
        return total

    async def budget_spent(self, session: Any, *, day: dt.date) -> dict[str, Decimal]:
        return {res: used for (row_day, res), used in self._view().items() if row_day == day}

    async def commit(self) -> None:
        self.rows.update(self._staged)
        self._staged.clear()

    async def rollback(self) -> None:
        self._staged.clear()

    async def __aenter__(self) -> Store:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> Store:
    shared = Store()
    monkeypatch.setattr(repo, "consume_budget", shared.consume_budget)
    monkeypatch.setattr(repo, "budget_spent", shared.budget_spent)
    return shared


def budget_on(store: Store, notify: Any = None) -> Budget:
    return Budget(sessions=cast(Any, lambda: store), notify=notify)


@pytest.fixture
def budget(store: Store) -> Budget:
    return budget_on(store)


def test_six_resources_match_the_spec_table(budget: Budget) -> None:
    assert {name: limit.limit for name, limit in budget.limits.items()} == SPEC_LIMITS


def test_on_exceed_actions_are_carried(budget: Budget) -> None:
    assert budget.limits["gpu_hours"].on_exceed == "reject_llm_call"
    assert budget.limits["robot_hours"].on_exceed == "sim_tasks_only"


def test_reset_is_midnight_in_the_zone_not_a_fixed_offset(budget: Budget) -> None:
    start = budget.window_start("day", dt.datetime(2026, 9, 16, 10, 0, tzinfo=TRT))
    assert (start.hour, start.minute) == (0, 0)
    assert start.tzinfo is not None and str(start.tzinfo) == "Europe/Istanbul"


def test_the_row_key_is_the_day_for_daily_and_the_month_for_monthly(budget: Budget) -> None:
    """SPEC 14.4: pcb_orders is monthly, so its row keys on the first of the month."""
    now = dt.datetime(2026, 9, 16, 10, 0, tzinfo=TRT)
    assert budget.period_key("sim_runs", now) == dt.date(2026, 9, 16)
    assert budget.period_key("pcb_orders", now) == dt.date(2026, 9, 1)


async def test_consume_under_the_limit(budget: Budget) -> None:
    assert await budget.consume("sim_runs", 100) == 0.5
    assert await budget.used("sim_runs") == 100


async def test_over_limit_raises_with_resource_and_reset_time(budget: Budget, store: Store) -> None:
    now = dt.datetime(2026, 9, 16, 23, 0, tzinfo=TRT)
    await budget.consume("gpu_hours", 5.5, now)
    with pytest.raises(BudgetExceeded) as excinfo:
        await budget.consume("gpu_hours", 1.0, now)
    error = excinfo.value
    assert error.resource == "gpu_hours"
    assert error.unit == "hours"
    assert error.on_exceed == "reject_llm_call"
    assert error.resets_at == dt.datetime(2026, 9, 17, 0, 0, tzinfo=TRT)
    assert error.used == 5.5, "the error reports the total before the refused charge"
    assert await budget.used("gpu_hours", now) == 5.5, "a refused request charges nothing"
    assert store.rows == {(dt.date(2026, 9, 16), "gpu_hours"): Decimal("5.5")}


async def test_a_restart_does_not_refund_the_window(store: Store) -> None:
    """T-084: 72 uninterrupted hours. A fresh process sees the same counters."""
    now = dt.datetime(2026, 9, 16, 9, 0, tzinfo=TRT)
    await budget_on(store).consume("llm_tokens", 400000, now)

    restarted = budget_on(store)
    assert await restarted.used("llm_tokens", now) == 400000
    with pytest.raises(BudgetExceeded):
        await restarted.consume("llm_tokens", 200000, now)


async def test_daily_window_rolls_over_at_local_midnight(budget: Budget) -> None:
    late = dt.datetime(2026, 9, 16, 23, 59, tzinfo=TRT)
    early = dt.datetime(2026, 9, 17, 0, 1, tzinfo=TRT)
    await budget.consume("llm_tokens", 400000, late)
    assert await budget.used("llm_tokens", late) == 400000
    assert await budget.used("llm_tokens", early) == 0
    assert await budget.consume("llm_tokens", 400000, early) == 0.8


async def test_pcb_orders_is_monthly(budget: Budget) -> None:
    first = dt.datetime(2026, 9, 1, 12, 0, tzinfo=TRT)
    later = dt.datetime(2026, 9, 28, 12, 0, tzinfo=TRT)
    next_month = dt.datetime(2026, 10, 2, 12, 0, tzinfo=TRT)
    await budget.consume("pcb_orders", 1, first)
    with pytest.raises(BudgetExceeded) as excinfo:
        await budget.consume("pcb_orders", 1, later)
    assert excinfo.value.resets_at == dt.datetime(2026, 10, 1, 0, 0, tzinfo=TRT)
    assert await budget.consume("pcb_orders", 1, next_month) == 1.0


async def test_notification_fires_once_at_ninety_percent(store: Store) -> None:
    seen: list[tuple[str, float]] = []
    budget = budget_on(store, notify=lambda resource, ratio: seen.append((resource, ratio)))
    now = dt.datetime(2026, 9, 16, 9, 0, tzinfo=TRT)
    await budget.consume("filament_grams", 400, now)
    assert seen == []
    await budget.consume("filament_grams", 50, now)
    assert seen == [("filament_grams", 0.9)]
    await budget.consume("filament_grams", 10, now)
    assert len(seen) == 1, "one notification per window"


async def test_notification_rearms_after_a_reset(store: Store) -> None:
    seen: list[tuple[str, float]] = []
    budget = budget_on(store, notify=lambda resource, ratio: seen.append((resource, ratio)))
    await budget.consume("robot_hours", 2.8, dt.datetime(2026, 9, 16, 9, 0, tzinfo=TRT))
    await budget.consume("robot_hours", 2.8, dt.datetime(2026, 9, 17, 9, 0, tzinfo=TRT))
    assert len(seen) == 2


async def test_used_ratio_metric_is_emitted(budget: Budget) -> None:
    await budget.consume("sim_runs", 50)
    assert REGISTRY.get_sample_value("neml_budget_used_ratio", {"resource": "sim_runs"}) == 0.25


async def test_snapshot_feeds_the_budget_endpoint(budget: Budget) -> None:
    now = dt.datetime(2026, 9, 16, 9, 0, tzinfo=TRT)
    await budget.consume("gpu_hours", 3, now)
    snapshot = await budget.snapshot(now)
    assert set(snapshot) == set(SPEC_LIMITS)
    assert snapshot["gpu_hours"]["unit"] == "hours"
    assert snapshot["gpu_hours"]["ratio"] == 0.5
    assert snapshot["pcb_orders"]["resets_at"] == "2026-10-01T00:00:00+03:00"
    assert snapshot["sim_runs"]["used"] == 0.0


async def test_unknown_resource_is_an_error(budget: Budget) -> None:
    with pytest.raises(KeyError):
        await budget.consume("bitcoin", 1)


# --------------------------------------------------------------------------------------
# ADR-011 / T-084: two consumers, one counter. A read-then-write pair lets both observe
# the same total and both pass the same limit check; the single upsert cannot. Needs a
# real PostgreSQL, so it runs on the lab host:
#   NEML_TEST_PG=1 python -m pytest brain/tests/runtime -m integration
# --------------------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("NEML_TEST_PG"), reason="needs Docker + PostgreSQL")
async def test_two_concurrent_consumers_cannot_both_take_the_last_unit() -> None:
    import asyncio

    from alembic.config import Config
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from testcontainers.postgres import PostgresContainer

    from alembic import command

    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        url = pg.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        os.environ["NEML_DB_URL"] = url
        command.upgrade(Config("brain/alembic.ini"), "head")

        engine = create_async_engine(url)
        try:
            # pcb_orders is 1 per month (SPEC 14.4): exactly one of the two may pass.
            budget = Budget(sessions=cast(Any, async_sessionmaker(engine)))
            outcomes = await asyncio.gather(
                budget.consume("pcb_orders", 1),
                budget.consume("pcb_orders", 1),
                return_exceptions=True,
            )
        finally:
            await engine.dispose()

    assert sorted(type(o).__name__ for o in outcomes) == ["BudgetExceeded", "float"]
    assert 1.0 in outcomes
