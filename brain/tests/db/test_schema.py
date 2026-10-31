# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# NEML_SPEC.md 7 is the contract, as amended by ADR-011 (skill_runs, budget_usage). Everything
# below is transcribed from the CREATE TABLE statements by hand -- never imported from
# models.py, or the test would only be checking that the code agrees with itself. Metadata
# introspection only: no live database.

from __future__ import annotations

import pathlib
import re

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from neml_brain.db.models import CLOUD_ONLY, Base

PG = postgresql.dialect()
VERSIONS = pathlib.Path(__file__).resolve().parents[3] / "brain/alembic/versions"
MIGRATION = VERSIONS / "0001_initial.py"
DECISION_2 = VERSIONS / "0003_skill_runs_budget_usage.py"

TZ = "TIMESTAMP WITH TIME ZONE"

# table -> [(column, compiled PostgreSQL type, nullable)]
SPEC_TABLES: dict[str, list[tuple[str, str, bool]]] = {
    "genomes": [
        ("id", "TEXT", False),
        ("name", "TEXT", False),
        ("version", "INTEGER", False),
        ("hash", "TEXT", False),
        ("parent_id", "TEXT", True),
        ("status", "TEXT", False),
        ("body", "JSONB", False),
        ("limits", "JSONB", False),
        ("fitness_score", "NUMERIC(6, 4)", True),
        ("created_at", TZ, False),
    ],
    "robots": [
        ("id", "TEXT", False),
        ("genome_id", "TEXT", False),
        ("namespace", "TEXT", False),
        ("hostname", "TEXT", False),
        ("state", "TEXT", False),
        ("battery_soc", "NUMERIC(4, 3)", True),
        ("last_seen", TZ, True),
        ("calibrated_at", TZ, True),
        ("reality_gap", "NUMERIC(5, 4)", True),
        ("created_at", TZ, False),
    ],
    "skills": [
        ("id", "TEXT", False),
        ("skill_key", "TEXT", False),
        ("version", "INTEGER", False),
        ("genome_id", "TEXT", False),
        ("bt_path", "TEXT", False),
        ("parameters", "JSONB", False),
        ("preconditions", "JSONB", False),
        ("status", "TEXT", False),
        ("supersedes", "TEXT", True),
        ("created_at", TZ, False),
    ],
    "skill_validations": [
        ("id", "BIGINT", False),
        ("skill_id", "TEXT", False),
        ("env", "TEXT", False),
        ("trials", "INTEGER", False),
        ("successes", "INTEGER", False),
        ("ci95_low", "NUMERIC(5, 4)", False),
        ("ci95_high", "NUMERIC(5, 4)", False),
        ("seeds", "INTEGER[]", False),
        ("failure_modes", "JSONB", False),
        ("run_at", TZ, False),
    ],
    # ADR-011 (amends SPEC 7): one trial per row, so "the last 20 runs" is countable.
    "skill_runs": [
        ("id", "BIGINT", False),
        ("skill_id", "TEXT", False),
        ("task_run_id", "BIGINT", True),
        ("env", "TEXT", False),
        ("seed", "BIGINT", True),
        ("success", "BOOLEAN", False),
        ("failure_mode", "TEXT", True),
        ("deterministic", "BOOLEAN", False),
        ("run_at", TZ, False),
    ],
    "tasks": [
        ("id", "UUID", False),
        ("title", "TEXT", False),
        ("kind", "TEXT", False),
        ("source", "TEXT", False),
        ("priority", "NUMERIC(6, 3)", False),
        ("state", "TEXT", False),
        ("robot_id", "TEXT", True),
        ("spec", "JSONB", False),
        ("result", "JSONB", True),
        ("deadline", TZ, True),
        ("created_at", TZ, False),
        ("updated_at", TZ, False),
    ],
    "task_runs": [
        ("id", "BIGINT", False),
        ("task_id", "UUID", False),
        ("attempt", "INTEGER", False),
        ("env", "TEXT", False),
        ("seed", "BIGINT", True),
        ("started_at", TZ, False),
        ("ended_at", TZ, True),
        ("outcome", "TEXT", True),
        ("metrics", "JSONB", True),
        ("rosbag_path", "TEXT", True),
    ],
    "campaigns": [
        ("id", "UUID", False),
        ("name", "TEXT", False),
        ("objective", "TEXT", False),
        ("weights", "JSONB", False),
        ("budget", "JSONB", False),
        ("state", "TEXT", False),
        ("started_at", TZ, False),
        ("ended_at", TZ, True),
    ],
    "candidates": [
        ("id", "UUID", False),
        ("campaign_id", "UUID", False),
        ("generation", "INTEGER", False),
        ("genome_id", "TEXT", False),
        ("operator", "TEXT", False),
        ("rationale", "TEXT", True),
        ("llm_model", "TEXT", True),
        ("prompt_hash", "TEXT", True),
        ("fitness", "NUMERIC(6, 4)", True),
        ("fitness_parts", "JSONB", True),
        ("verdict", "TEXT", True),
        ("created_at", TZ, False),
    ],
    "sim_runs": [
        ("id", "BIGINT", False),
        ("candidate_id", "UUID", True),
        ("world_id", "TEXT", False),
        ("seed", "BIGINT", False),
        ("profile", "TEXT", False),
        ("sim_version", "TEXT", False),
        ("duration_s", "NUMERIC(8, 2)", True),
        ("metrics", "JSONB", False),
        ("deterministic", "BOOLEAN", False),
        ("run_at", TZ, False),
    ],
    "artifacts": [
        ("id", "UUID", False),
        ("kind", "TEXT", False),
        ("path", "TEXT", False),
        ("sha256", "TEXT", False),
        ("genome_id", "TEXT", True),
        ("generator", "TEXT", False),
        ("input_hash", "TEXT", True),
        ("llm_model", "TEXT", True),
        ("created_at", TZ, False),
    ],
    "print_jobs": [
        ("id", "UUID", False),
        ("artifact_id", "UUID", False),
        ("printer_id", "TEXT", False),
        ("profile_id", "TEXT", False),
        ("approval_id", "UUID", False),
        ("est_time_h", "NUMERIC(6, 2)", True),
        ("est_filament_g", "NUMERIC(8, 2)", True),
        ("est_cost_try", "NUMERIC(10, 2)", True),
        ("state", "TEXT", False),
        ("qc", "JSONB", True),
        ("started_at", TZ, True),
        ("ended_at", TZ, True),
    ],
    "bom_items": [
        ("id", "BIGINT", False),
        ("genome_id", "TEXT", False),
        ("ref", "TEXT", False),
        ("part_number", "TEXT", False),
        ("qty", "INTEGER", False),
        ("unit_cost_try", "NUMERIC(10, 2)", True),
        ("supplier", "TEXT", True),
        ("lead_time_days", "INTEGER", True),
    ],
    "telemetry": [
        ("ts", TZ, False),
        ("robot_id", "TEXT", False),
        ("metric", "TEXT", False),
        ("value", "DOUBLE PRECISION", False),
        ("tags", "JSONB", True),
    ],
    # ADR-011 (amends SPEC 7): SPEC 14.4 counters that survive a restart (T-084).
    "budget_usage": [
        ("day", "DATE", False),
        ("resource", "TEXT", False),
        ("used", "NUMERIC(14, 4)", False),
    ],
    "approvals": [
        ("id", "UUID", False),
        ("level", "INTEGER", False),
        ("subject_kind", "TEXT", False),
        ("subject_id", "TEXT", False),
        ("payload", "JSONB", False),
        ("requested_at", TZ, False),
        ("expires_at", TZ, False),
        ("decided_at", TZ, True),
        ("decided_by", "TEXT", True),
        ("decision", "TEXT", True),
        ("note", "TEXT", True),
    ],
    "safety_checks": [
        ("id", "BIGINT", False),
        ("robot_id", "TEXT", False),
        ("estop_ok", "BOOLEAN", False),
        ("watchdog_ok", "BOOLEAN", False),
        ("current_limit_ok", "BOOLEAN", False),
        ("performed_by", "TEXT", False),
        ("performed_at", TZ, False),
    ],
    "audit_log": [
        ("id", "BIGINT", False),
        ("ts", TZ, False),
        ("actor", "TEXT", False),
        ("action", "TEXT", False),
        ("target", "TEXT", True),
        ("params_hash", "TEXT", True),
        ("outcome", "TEXT", True),
        ("duration_ms", "INTEGER", True),
        ("approval_id", "UUID", True),
    ],
    "memory_chunks": [
        ("id", "BIGINT", False),
        ("source_kind", "TEXT", False),
        ("source_id", "TEXT", True),
        ("content", "TEXT", False),
        ("embedding", "vector(384)", False),
        ("created_at", TZ, False),
    ],
    "users": [
        ("id", "UUID", False),
        ("email", "TEXT", False),
        ("password_hash", "TEXT", False),
        ("role", "TEXT", False),
        ("created_at", TZ, False),
    ],
    "devices": [
        ("id", "UUID", False),
        ("user_id", "UUID", False),
        ("platform", "TEXT", False),
        ("push_token", "TEXT", True),
        ("last_seen", TZ, True),
    ],
    "commands": [
        ("id", "UUID", False),
        ("user_id", "UUID", False),
        ("idempotency_key", "TEXT", False),
        ("seq", "BIGINT", False),
        ("kind", "TEXT", False),
        ("payload", "JSONB", False),
        ("state", "TEXT", False),
        ("result", "JSONB", True),
        ("created_at", TZ, False),
        ("applied_at", TZ, True),
    ],
}

# Every CHECK in SPEC 7, by the name PostgreSQL gives an inline column CHECK.
SPEC_CHECKS: dict[str, str] = {
    "genomes_status_check": "status IN ('draft','testing','active','deprecated')",
    "robots_state_check": (
        "state IN ('offline','idle','charging','running','fault','estop','maintenance')"
    ),
    "skills_status_check": "status IN ('candidate','validated','retired')",
    "skill_validations_env_check": "env IN ('sim','real')",
    "skill_validations_trials_check": "trials > 0",
    "skill_runs_env_check": "env IN ('sim','real')",
    "tasks_kind_check": (
        "kind IN ('human','repair','exploration','evolution','maintenance','calibration')"
    ),
    "tasks_state_check": (
        "state IN ('queued','planning','awaiting_approval','running','paused',"
        "'succeeded','failed','cancelled')"
    ),
    "task_runs_env_check": "env IN ('sim','bench','tethered','free')",
    "task_runs_outcome_check": "outcome IN ('success','failure','aborted','timeout')",
    "campaigns_state_check": "state IN ('active','stopped','completed')",
    "candidates_operator_check": "operator IN ('mutation','crossover','llm_guided','seed')",
    "candidates_verdict_check": (
        "verdict IN ('pending','sim_pass','sim_fail','real_pass','real_fail','accepted','rejected')"
    ),
    "sim_runs_profile_check": "profile IN ('fast','lidar','visual')",
    "artifacts_kind_check": (
        "kind IN ('cad_src','step','stl','3mf','gcode','kicad','gerber','bom','urdf','bt')"
    ),
    "print_jobs_state_check": "state IN ('queued','printing','done','failed','cancelled')",
    "approvals_level_check": "level BETWEEN 1 AND 4",
    "approvals_decision_check": "decision IN ('approved','rejected','expired')",
    "users_role_check": "role IN ('owner','operator','viewer')",
    "devices_platform_check": "platform IN ('android','ios','web')",
    "commands_state_check": "state IN ('pending','delivered','applied','failed','rejected')",
}

SPEC_INDEXES = {
    "genomes_status_idx",
    "genomes_parent_id_idx",
    "skill_runs_skill_id_run_at_idx",
    "tasks_state_priority_idx",
    "telemetry_robot_id_metric_ts_idx",
    "audit_log_ts_idx",
    "memory_chunks_embedding_idx",
    "commands_state_seq_idx",
}


def _squash(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def test_every_spec_table_is_mapped() -> None:
    assert set(Base.metadata.tables) == set(SPEC_TABLES)


@pytest.mark.parametrize("table_name", sorted(SPEC_TABLES))
def test_table_columns_match_spec(table_name: str) -> None:
    table = Base.metadata.tables[table_name]
    expected = SPEC_TABLES[table_name]
    assert [c.name for c in table.columns] == [name for name, _, _ in expected]
    for name, type_sql, nullable in expected:
        column = table.columns[name]
        assert column.type.compile(dialect=PG) == type_sql, f"{table_name}.{name} type"
        assert column.nullable is nullable, f"{table_name}.{name} nullability"


def test_check_constraints_match_spec() -> None:
    found = {
        constraint.name: _squash(str(constraint.sqltext))
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, sa.CheckConstraint) and constraint.name
    }
    assert found == {name: _squash(sql) for name, sql in SPEC_CHECKS.items()}


def test_indexes_match_spec() -> None:
    found = {index.name for table in Base.metadata.tables.values() for index in table.indexes}
    assert found == SPEC_INDEXES


def test_telemetry_is_range_partitioned_on_ts() -> None:
    # SPEC 7: ") PARTITION BY RANGE (ts)". The PK-less table gets a mapper-only key.
    table = Base.metadata.tables["telemetry"]
    assert table.dialect_options["postgresql"]["partition_by"] == "RANGE (ts)"
    assert not table.primary_key.columns


def test_cloud_only_tables() -> None:
    # SPEC 7: the schema is shared; neml_cloud is the one that carries these.
    assert CLOUD_ONLY == {"users", "devices", "commands"}
    assert CLOUD_ONLY <= set(SPEC_TABLES)


def test_memory_chunks_uses_hnsw_cosine_index() -> None:
    index = next(
        i
        for i in Base.metadata.tables["memory_chunks"].indexes
        if i.name == "memory_chunks_embedding_idx"
    )
    options = index.dialect_options["postgresql"]
    assert options["using"] == "hnsw"
    assert options["ops"] == {"embedding": "vector_cosine_ops"}


DECISION_2_TABLES = {"skill_runs", "budget_usage"}


def test_migrations_create_every_mapped_table() -> None:
    sql = "\n".join(p.read_text(encoding="utf-8") for p in sorted(VERSIONS.glob("0*.py")))
    for table_name in SPEC_TABLES:
        assert f"CREATE TABLE {table_name} (" in sql, table_name
    for index_name in SPEC_INDEXES:
        assert f"CREATE INDEX {index_name} ON " in sql, index_name


def test_initial_migration_owns_the_original_spec_7_tables() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    for table_name in SPEC_TABLES.keys() - DECISION_2_TABLES:
        assert f"CREATE TABLE {table_name} (" in sql, table_name
    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql
    assert "CREATE EXTENSION IF NOT EXISTS pgcrypto" in sql
    assert "PARTITION BY RANGE (ts)" in sql
    assert "neml_ensure_telemetry_partition" in sql


def test_decision_2_migration_adds_both_tables_with_index_and_composite_pk() -> None:
    # ADR-011: 0003 is the only place these two tables come from, and it follows 0002.
    sql = DECISION_2.read_text(encoding="utf-8")
    assert 'revision: str = "0003"' in sql
    assert 'down_revision: str | None = "0002"' in sql
    assert "CREATE TABLE skill_runs (" in sql
    assert "task_run_id     BIGINT REFERENCES task_runs(id)" in sql
    assert "CHECK (env IN ('sim','real'))" in sql
    assert "deterministic   BOOLEAN NOT NULL DEFAULT TRUE" in sql
    assert (
        "CREATE INDEX skill_runs_skill_id_run_at_idx ON skill_runs (skill_id, run_at DESC)" in sql
    )
    assert "CREATE TABLE budget_usage (" in sql
    assert "used            NUMERIC(14,4) NOT NULL DEFAULT 0" in sql
    assert "PRIMARY KEY (day, resource)" in sql


def test_budget_usage_primary_key_is_day_plus_resource() -> None:
    table = Base.metadata.tables["budget_usage"]
    assert [c.name for c in table.primary_key.columns] == ["day", "resource"]


def test_skill_runs_index_is_skill_id_then_newest_first() -> None:
    index = next(
        i
        for i in Base.metadata.tables["skill_runs"].indexes
        if i.name == "skill_runs_skill_id_run_at_idx"
    )
    assert [str(e) for e in index.expressions] == ["skill_runs.skill_id", "run_at DESC"]


def test_weights_lock_migration_has_no_state_escape_hatch() -> None:
    # T-090 / SPEC 14.3: the trigger fires on every UPDATE, whatever the campaign state is.
    path = MIGRATION.with_name("0002_weights_lock.py")
    lines = path.read_text(encoding="utf-8").splitlines()
    sql = "\n".join(line for line in lines if not line.lstrip().startswith("#"))
    assert "BEFORE UPDATE ON campaigns" in sql
    assert "NEW.weights IS DISTINCT FROM OLD.weights" in sql
    assert "RAISE EXCEPTION" in sql
    assert "state <>" not in sql and "state =" not in sql
