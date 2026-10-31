# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# The repo queries carry real SPEC rules (14.2 ordering, 14.4 windows, 14.6 rolling rate), so
# they are checked by compiling the statement a fake session captures. No database needed.
# The one test that genuinely needs PostgreSQL -- the SPEC 14.3 / T-090 weights trigger -- is
# marked `integration` and only runs with NEML_TEST_PG=1 and Docker available.

from __future__ import annotations

import datetime as dt
import os
import pathlib
import types
from decimal import Decimal
from typing import Any

import pytest
import yaml
from sqlalchemy.dialects import postgresql

from neml_brain.db import repo

PG = postgresql.dialect()
T0 = dt.datetime(2026, 2, 1, tzinfo=dt.UTC)
T1 = dt.datetime(2026, 3, 1, tzinfo=dt.UTC)
DAY = dt.date(2026, 2, 1)
BUDGET_YAML = pathlib.Path(__file__).resolve().parents[3] / "config/budget.yaml"


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value
        self.rowcount = 0

    def scalar_one_or_none(self) -> Any:
        return self._value

    def scalar_one(self) -> Any:
        return self._value

    def __iter__(self) -> Any:
        return iter(self._value or [])

    def scalars(self) -> _Result:
        return self

    def all(self) -> Any:
        return self._value or []

    def one(self) -> Any:
        return self._value


class _Session:
    """Captures the statement instead of running it."""

    def __init__(self, value: Any = None) -> None:
        self.statements: list[Any] = []
        self._value = value

    async def execute(self, statement: Any) -> _Result:
        self.statements.append(statement)
        return _Result(self._value)


async def _sql(coro_factory: Any, session: _Session) -> str:
    await coro_factory
    return str(session.statements[-1].compile(dialect=PG))


async def test_next_task_uses_spec_14_2_ordering() -> None:
    session = _Session()
    sql = await _sql(repo.next_task(session), session)  # type: ignore[arg-type]
    assert "tasks.state = " in sql
    assert "ORDER BY tasks.priority DESC, tasks.created_at ASC" in sql
    assert "LIMIT" in sql


async def test_pending_approvals_filters_undecided_and_unexpired() -> None:
    session = _Session([])
    sql = await _sql(repo.pending_approvals(session, now=T0), session)  # type: ignore[arg-type]
    assert "approvals.decision IS NULL" in sql
    assert "approvals.expires_at > " in sql
    assert "ORDER BY approvals.requested_at ASC" in sql


async def test_expire_approvals_marks_expired() -> None:
    session = _Session()
    sql = await _sql(repo.expire_approvals(session, now=T0), session)  # type: ignore[arg-type]
    assert sql.startswith("UPDATE approvals SET")
    assert "approvals.expires_at <= " in sql


async def test_budget_usage_covers_the_spec_14_4_resources() -> None:
    row = types.SimpleNamespace(
        sim_runs=7, robot_seconds=7200.0, filament_grams=125.5, pcb_orders=1
    )
    session = _Session(row)
    usage = await repo.budget_usage(session, day_start=T0, month_start=T0)  # type: ignore[arg-type]
    assert usage == {
        "sim_runs": 7.0,
        "robot_hours": 2.0,
        "filament_grams": 125.5,
        "pcb_orders": 1.0,
    }
    sql = str(session.statements[-1].compile(dialect=PG))
    # Physical robot time only counts the non-sim environments (SPEC 7 task_runs.env).
    assert "task_runs.env IN " in sql
    assert "sim_runs.run_at >= " in sql
    assert "print_jobs.est_filament_g" in sql
    assert "approvals.subject_kind = " in sql


async def test_skill_success_rate_is_a_20_run_rolling_window_over_skill_runs() -> None:
    # ADR-011: one skill_runs row is one trial, so "the last 20 runs" is literal.
    session = _Session(0.65)
    rate = await repo.skill_success_rate(session, "climb_small_obstacle@3")  # type: ignore[arg-type]
    assert rate == 0.65
    sql = str(session.statements[-1].compile(dialect=PG, compile_kwargs={"literal_binds": True}))
    assert "FROM skill_runs" in sql
    assert "skill_validations" not in sql  # the old aggregate approximation is gone
    assert "ORDER BY skill_runs.run_at DESC, skill_runs.id DESC" in sql
    assert "LIMIT 20" in sql


async def test_skill_success_rate_excludes_non_deterministic_runs() -> None:
    """SPEC 11.2 rule 3: the filter lives in the query, not in the caller."""
    session = _Session(1.0)
    await repo.skill_success_rate(session, "walk_flat@4")  # type: ignore[arg-type]
    sql = str(session.statements[-1].compile(dialect=PG, compile_kwargs={"literal_binds": True}))
    assert "skill_runs.deterministic IS true" in sql


async def test_skill_success_rate_is_none_without_runs() -> None:
    session = _Session(None)
    assert await repo.skill_success_rate(session, "nope@1") is None  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# SPEC 14.4 / T-084 budget counters (ADR-011).
# --------------------------------------------------------------------------------------
def test_budget_resource_keys_come_from_config_budget_yaml() -> None:
    """budget_usage.resource carries config/budget.yaml's names verbatim -- nothing invents
    its own spelling, or a limit check would silently read a counter nobody charges."""
    limits = yaml.safe_load(BUDGET_YAML.read_text(encoding="utf-8"))["limits"]
    assert set(limits) == {
        "gpu_hours",
        "sim_runs",
        "robot_hours",
        "filament_grams",
        "pcb_orders",
        "llm_tokens",
    }


@pytest.mark.parametrize(
    "resource",
    ["gpu_hours", "sim_runs", "robot_hours", "filament_grams", "pcb_orders", "llm_tokens"],
)
async def test_consume_budget_is_one_upsert_statement(resource: str) -> None:
    session = _Session(Decimal("3.0000"))
    used = await repo.consume_budget(  # type: ignore[arg-type]
        session, resource=resource, amount=Decimal("1"), day=DAY
    )
    assert used == Decimal("3.0000")
    assert len(session.statements) == 1  # read-then-write would be two
    sql = str(session.statements[-1].compile(dialect=PG))
    assert sql.startswith("INSERT INTO budget_usage")
    assert "ON CONFLICT (day, resource) DO UPDATE SET used = (budget_usage.used +" in sql
    assert "RETURNING budget_usage.used" in sql
    # The increment is the stored value plus the amount, never the proposed row's value.
    assert "excluded" not in sql


async def test_budget_spent_reads_one_days_counters() -> None:
    session = _Session([types.SimpleNamespace(resource="sim_runs", used=Decimal("12.0000"))])
    spent = await repo.budget_spent(session, day=DAY)  # type: ignore[arg-type]
    assert spent == {"sim_runs": Decimal("12.0000")}
    sql = str(session.statements[-1].compile(dialect=PG))
    assert "FROM budget_usage" in sql
    assert "budget_usage.day = " in sql


async def test_telemetry_range_is_half_open_and_ordered() -> None:
    session = _Session([])
    sql = await _sql(
        repo.telemetry_range(session, robot_id="R01", metric="battery_soc", start=T0, end=T1),  # type: ignore[arg-type]
        session,
    )
    assert "telemetry.ts >= " in sql
    assert "telemetry.ts < " in sql
    assert "ORDER BY telemetry.ts ASC" in sql


async def test_telemetry_after_cursor_is_exclusive() -> None:
    session = _Session([])
    sql = await _sql(
        repo.telemetry_range(
            session,
            robot_id="R01",
            metric="battery_soc",
            start=T0,
            end=T1,
            after=T0,  # type: ignore[arg-type]
        ),
        session,
    )
    assert "telemetry.ts > " in sql


# --------------------------------------------------------------------------------------
# SPEC 14.3 / T-090: "campaign weights cannot be changed after the campaign starts
# (DB trigger test)". Needs a real PostgreSQL 16 + pgvector.
#   NEML_TEST_PG=1 python -m pytest brain/tests/db -m integration
# --------------------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("NEML_TEST_PG"), reason="needs Docker + PostgreSQL")
@pytest.mark.parametrize("state", ["active", "stopped", "completed"])
def test_campaign_weights_are_immutable_in_every_state(state: str) -> None:
    import sqlalchemy as sa
    from alembic.config import Config
    from testcontainers.postgres import PostgresContainer

    from alembic import command

    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        url = pg.get_connection_url()  # psycopg2 URL
        os.environ["NEML_DB_URL"] = url.replace("postgresql+psycopg2", "postgresql+asyncpg")
        command.upgrade(Config("brain/alembic.ini"), "head")

        engine = sa.create_engine(url)
        with engine.begin() as conn:
            campaign_id = conn.execute(
                sa.text(
                    "INSERT INTO campaigns (name, objective, weights, budget, state) "
                    "VALUES ('c', 'o', '{\"success\": 0.40}', '{}', :s) RETURNING id"
                ),
                {"s": state},
            ).scalar_one()

            # Everything but weights stays editable.
            conn.execute(
                sa.text("UPDATE campaigns SET objective = 'o2' WHERE id = :i"), {"i": campaign_id}
            )

        with engine.begin() as conn, pytest.raises(sa.exc.DBAPIError, match="immutable"):
            conn.execute(
                sa.text("UPDATE campaigns SET weights = '{\"success\": 0.90}' WHERE id = :i"),
                {"i": campaign_id},
            )


# --------------------------------------------------------------------------------------
# ADR-011 / T-084: two consumers, one counter. A read-then-write pair lets both of them
# observe the same total and both pass the same limit check; the single upsert cannot.
# Needs a real PostgreSQL, so it runs on the lab host:
#   NEML_TEST_PG=1 python -m pytest brain/tests/db -m integration
# --------------------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("NEML_TEST_PG"), reason="needs Docker + PostgreSQL")
async def test_consume_budget_is_atomic_across_two_sessions() -> None:
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
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with sessions() as a, sessions() as b:
                charge = {"resource": "sim_runs", "amount": Decimal("1"), "day": DAY}
                assert await repo.consume_budget(a, **charge) == Decimal("1.0000")

                # B hits the same key while A still holds it: the upsert blocks, it does not
                # read a stale 1 and write its own 1.
                second = asyncio.create_task(repo.consume_budget(b, **charge))
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(second), timeout=2.0)

                await a.commit()
                assert await second == Decimal("2.0000")  # stacked, not lost
                await b.commit()

            async with sessions() as c:
                assert await repo.budget_spent(c, day=DAY) == {"sim_runs": Decimal("2.0000")}
        finally:
            await engine.dispose()
