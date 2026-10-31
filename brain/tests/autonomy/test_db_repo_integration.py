# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""AutonomyRepo and SettingsStore SQL against a real PostgreSQL 16 + pgvector.

The statements are plain SQL, so the only honest check is to run them. CI starts
the container (testcontainers); locally:

    NEML_TEST_PG=1 python -m pytest brain/tests/autonomy/test_db_repo_integration.py -m integration
"""

import os
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("NEML_TEST_PG"), reason="needs Docker + PostgreSQL"),
]

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def url():
    from alembic.config import Config
    from testcontainers.postgres import PostgresContainer

    from alembic import command

    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        sync = pg.get_connection_url()
        async_url = sync.replace("postgresql+psycopg2", "postgresql+asyncpg")
        os.environ["NEML_DB_URL"] = async_url
        command.upgrade(Config("brain/alembic.ini"), "head")
        yield async_url


@pytest.fixture
async def repo(url):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from neml_brain.autonomy.db_repo import AutonomyRepo
    from neml_brain.settings.store import SettingsStore

    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    yield AutonomyRepo(sessions, SettingsStore(sessions)), sessions
    await engine.dispose()


async def _seed_robot(sessions):
    import sqlalchemy as sa

    async with sessions() as s:
        await s.execute(
            sa.text(
                "INSERT INTO genomes (id, name, version, hash, status, body, limits)"
                " VALUES ('g1', 'quadruped_v2', 1, 'h1', 'active', '{}', '{}')"
                " ON CONFLICT DO NOTHING"
            )
        )
        await s.execute(
            sa.text(
                "INSERT INTO robots (id, genome_id, namespace, hostname, state, battery_soc,"
                " calibrated_at, reality_gap)"
                " VALUES ('R01', 'g1', '/r01', 'r01.lab', 'idle', 0.20, :cal, 0.31)"
                " ON CONFLICT DO NOTHING"
            ),
            {"cal": NOW - timedelta(days=30)},
        )
        await s.commit()


async def test_queue_dedupe_claim_record_judge_and_retry(repo):
    from neml_brain.autonomy.discovery import TaskProposal
    from neml_brain.autonomy.learning import TaskOutcome

    r, _ = repo
    low = TaskProposal(
        "low", "exploration", "auto:coverage", 10.0, {"world_id": "flat"}, "k:low", NOW
    )
    high = TaskProposal(
        "high", "exploration", "auto:coverage", 90.0, {"world_id": "maze"}, "k:high", NOW
    )
    await r.create_task(low)
    task_id = await r.create_task(high)
    assert {"k:low", "k:high"} <= await r.open_task_keys()

    claimed = await r.claim_next_task()
    assert claimed and claimed["id"] == task_id and claimed["spec"]["world_id"] == "maze"

    run = TaskOutcome(
        task_id, 1, "sim", NOW, NOW + timedelta(seconds=30), "failure", metrics={"x": 1}
    )
    run_id = await r.record_run(run)
    await r.save_verdict(run_id, False, ["executor outcome: failure"], "retry")
    await r.save_verdict(run_id, False, ["executor outcome: failure"], "retry")  # idempotent
    assert await r.attempts(task_id) == 1

    await r.requeue(task_id, {"world_id": "maze", "seed": 1})
    again = await r.claim_next_task()
    assert again and again["id"] == task_id and again["spec"]["seed"] == 1

    history = await r.judged_history()
    assert [(h.kind, h.done) for h in history] == [("exploration", False)]
    assert history[0].duration_s == pytest.approx(30)


async def test_factors_round_trip_and_survive_upsert(repo):
    from neml_brain.autonomy.discovery import Factors
    from neml_brain.autonomy.tuning import as_rows

    r, _ = repo
    base = await r.load_factors()
    assert base.g("exploration") == 0.30  # the prior until something is fitted
    fitted = Factors(gain={"exploration": 0.7}, cheap={"exploration": 0.2})
    await r.save_factors(as_rows(fitted, {"exploration": 12}))
    await r.save_factors(as_rows(fitted, {"exploration": 13}))
    loaded = await r.load_factors()
    assert loaded.g("exploration") == 0.7 and loaded.c("exploration") == 0.2


async def test_robot_health_withholds_the_mtbf_decision_until_the_owner_sets_it(repo):
    import sqlalchemy as sa

    r, sessions = repo
    await _seed_robot(sessions)
    async with sessions() as s:
        task_id = (
            await s.execute(
                sa.text(
                    "INSERT INTO tasks (title, kind, source, priority, state, robot_id, spec)"
                    " VALUES ('walk', 'human', 'user:mg', 50, 'succeeded', 'R01', '{}')"
                    " RETURNING id"
                )
            )
        ).scalar_one()
        for attempt in (1, 2):  # two failures over two hours: MTBF 1 h
            await s.execute(
                sa.text(
                    "INSERT INTO task_runs (task_id, attempt, env, started_at, ended_at, outcome)"
                    " VALUES (:t, :a, 'free', :s, :e, 'failure')"
                ),
                {"t": task_id, "a": attempt, "s": NOW, "e": NOW + timedelta(hours=1)},
            )
        await s.commit()

    (health,) = [h for h in await r.robot_health() if h.robot_id == "R01"]
    assert health.mtbf_below_threshold is False  # no mtbf_min_hours entered yet

    await r._settings.put("quadruped_v2", {"mtbf_min_hours": 5}, "owner@firm.com")
    (health,) = [h for h in await r.robot_health() if h.robot_id == "R01"]
    assert health.mtbf_below_threshold is True and health.calibration_max_days == 7


async def test_coverage_battery_and_settings(repo):
    r, sessions = repo
    await _seed_robot(sessions)
    cells = {c.world_id: c.last_tried_at for c in await r.coverage_cells()}
    assert set(cells) == {"flat", "maze", "obstacle_low", "ramp_10deg", "rough_terrain"}
    assert (await r.robot_batteries())["R01"] == pytest.approx(0.20)

    store = r._settings
    assert "quadruped_v2" in await store.model_ids() and (await store.model_ids())[0] == "_lab"
    await store.put("_lab", {"filament_try_per_kg_pla": 600}, "owner@firm.com")
    await store.put("_lab", {"filament_try_per_kg_pla": None}, "owner@firm.com")  # null clears
    assert await store.get("_lab") == {}
