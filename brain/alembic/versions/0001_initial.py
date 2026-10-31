# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# initial schema (SPEC 7)
#
# The DDL below is SPEC 7 verbatim, one statement per list entry (asyncpg refuses
# multi-statement execute). Raw SQL on purpose: SPEC 7 *is* the contract, so translating it
# through op.create_table() would only add a place for it to drift.
#
# Revision ID: 0001
# Revises:
# Create Date: 2026-02-10

from __future__ import annotations

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


STATEMENTS: list[str] = [
    "CREATE EXTENSION IF NOT EXISTS vector",
    "CREATE EXTENSION IF NOT EXISTS pgcrypto",
    # ============ ROBOT & GENOME ============
    """
    CREATE TABLE genomes (
        id              TEXT PRIMARY KEY,
        name            TEXT NOT NULL,
        version         INT  NOT NULL,
        hash            TEXT NOT NULL UNIQUE,
        parent_id       TEXT REFERENCES genomes(id),
        status          TEXT NOT NULL CHECK (status IN ('draft','testing','active','deprecated')),
        body            JSONB NOT NULL,
        limits          JSONB NOT NULL,
        fitness_score   NUMERIC(6,4),
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX genomes_status_idx ON genomes (status)",
    "CREATE INDEX genomes_parent_id_idx ON genomes (parent_id)",
    """
    CREATE TABLE robots (
        id              TEXT PRIMARY KEY,
        genome_id       TEXT NOT NULL REFERENCES genomes(id),
        namespace       TEXT NOT NULL UNIQUE,
        hostname        TEXT NOT NULL,
        state           TEXT NOT NULL CHECK (state IN
                          ('offline','idle','charging','running','fault','estop','maintenance')),
        battery_soc     NUMERIC(4,3),
        last_seen       TIMESTAMPTZ,
        calibrated_at   TIMESTAMPTZ,
        reality_gap     NUMERIC(5,4),
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # ============ SKILL ============
    """
    CREATE TABLE skills (
        id              TEXT PRIMARY KEY,
        skill_key       TEXT NOT NULL,
        version         INT  NOT NULL,
        genome_id       TEXT NOT NULL REFERENCES genomes(id),
        bt_path         TEXT NOT NULL,
        parameters      JSONB NOT NULL,
        preconditions   JSONB NOT NULL,
        status          TEXT NOT NULL CHECK (status IN ('candidate','validated','retired')),
        supersedes      TEXT REFERENCES skills(id),
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (skill_key, version)
    )
    """,
    """
    CREATE TABLE skill_validations (
        id              BIGSERIAL PRIMARY KEY,
        skill_id        TEXT NOT NULL REFERENCES skills(id),
        env             TEXT NOT NULL CHECK (env IN ('sim','real')),
        trials          INT  NOT NULL CHECK (trials > 0),
        successes       INT  NOT NULL,
        ci95_low        NUMERIC(5,4) NOT NULL,
        ci95_high       NUMERIC(5,4) NOT NULL,
        seeds           INT[] NOT NULL,
        failure_modes   JSONB NOT NULL DEFAULT '[]',
        run_at          TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # ============ TASK ============
    """
    CREATE TABLE tasks (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        title           TEXT NOT NULL,
        kind            TEXT NOT NULL CHECK (kind IN
                          ('human','repair','exploration','evolution','maintenance','calibration')),
        source          TEXT NOT NULL,
        priority        NUMERIC(6,3) NOT NULL,
        state           TEXT NOT NULL CHECK (state IN
                          ('queued','planning','awaiting_approval','running','paused',
                           'succeeded','failed','cancelled')),
        robot_id        TEXT REFERENCES robots(id),
        spec            JSONB NOT NULL,
        result          JSONB,
        deadline        TIMESTAMPTZ,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX tasks_state_priority_idx ON tasks (state, priority DESC)",
    """
    CREATE TABLE task_runs (
        id              BIGSERIAL PRIMARY KEY,
        task_id         UUID NOT NULL REFERENCES tasks(id),
        attempt         INT  NOT NULL,
        env             TEXT NOT NULL CHECK (env IN ('sim','bench','tethered','free')),
        seed            BIGINT,
        started_at      TIMESTAMPTZ NOT NULL,
        ended_at        TIMESTAMPTZ,
        outcome         TEXT CHECK (outcome IN ('success','failure','aborted','timeout')),
        metrics         JSONB,
        rosbag_path     TEXT,
        UNIQUE (task_id, attempt)
    )
    """,
    # ============ EVOLUTION ============
    """
    CREATE TABLE campaigns (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name            TEXT NOT NULL,
        objective       TEXT NOT NULL,
        weights         JSONB NOT NULL,
        budget          JSONB NOT NULL,
        state           TEXT NOT NULL CHECK (state IN ('active','stopped','completed')),
        started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        ended_at        TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE candidates (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        campaign_id     UUID NOT NULL REFERENCES campaigns(id),
        generation      INT  NOT NULL,
        genome_id       TEXT NOT NULL REFERENCES genomes(id),
        operator        TEXT NOT NULL CHECK (operator IN
                          ('mutation','crossover','llm_guided','seed')),
        rationale       TEXT,
        llm_model       TEXT,
        prompt_hash     TEXT,
        fitness         NUMERIC(6,4),
        fitness_parts   JSONB,
        verdict         TEXT CHECK (verdict IN ('pending','sim_pass','sim_fail',
                                                'real_pass','real_fail','accepted','rejected')),
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE sim_runs (
        id              BIGSERIAL PRIMARY KEY,
        candidate_id    UUID REFERENCES candidates(id),
        world_id        TEXT NOT NULL,
        seed            BIGINT NOT NULL,
        profile         TEXT NOT NULL CHECK (profile IN ('fast','lidar','visual')),
        sim_version     TEXT NOT NULL,
        duration_s      NUMERIC(8,2),
        metrics         JSONB NOT NULL,
        deterministic   BOOLEAN NOT NULL DEFAULT TRUE,
        run_at          TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # ============ MANUFACTURING ============
    """
    CREATE TABLE artifacts (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        kind            TEXT NOT NULL CHECK (kind IN
                          ('cad_src','step','stl','3mf','gcode','kicad','gerber','bom','urdf','bt')),
        path            TEXT NOT NULL,
        sha256          TEXT NOT NULL,
        genome_id       TEXT REFERENCES genomes(id),
        generator       TEXT NOT NULL,
        input_hash      TEXT,
        llm_model       TEXT,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE print_jobs (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        artifact_id     UUID NOT NULL REFERENCES artifacts(id),
        printer_id      TEXT NOT NULL,
        profile_id      TEXT NOT NULL,
        approval_id     UUID NOT NULL,
        est_time_h      NUMERIC(6,2),
        est_filament_g  NUMERIC(8,2),
        est_cost_try    NUMERIC(10,2),
        state           TEXT NOT NULL CHECK (state IN
                          ('queued','printing','done','failed','cancelled')),
        qc              JSONB,
        started_at      TIMESTAMPTZ,
        ended_at        TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE bom_items (
        id              BIGSERIAL PRIMARY KEY,
        genome_id       TEXT NOT NULL REFERENCES genomes(id),
        ref             TEXT NOT NULL,
        part_number     TEXT NOT NULL,
        qty             INT NOT NULL,
        unit_cost_try   NUMERIC(10,2),
        supplier        TEXT,
        lead_time_days  INT
    )
    """,
    # ============ TELEMETRY (monthly partitions) ============
    """
    CREATE TABLE telemetry (
        ts              TIMESTAMPTZ NOT NULL,
        robot_id        TEXT NOT NULL,
        metric          TEXT NOT NULL,
        value           DOUBLE PRECISION NOT NULL,
        tags            JSONB
    ) PARTITION BY RANGE (ts)
    """,
    "CREATE INDEX telemetry_robot_id_metric_ts_idx ON telemetry (robot_id, metric, ts DESC)",
    # scripts/db/create_partitions.sh calls this every month (systemd timer).
    """
    CREATE OR REPLACE FUNCTION neml_ensure_telemetry_partition(p_month date)
    RETURNS text LANGUAGE plpgsql AS $$
    DECLARE
        m    date := date_trunc('month', p_month)::date;
        part text := 'telemetry_' || to_char(m, 'YYYY_MM');
    BEGIN
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS %I PARTITION OF telemetry FOR VALUES FROM (%L) TO (%L)',
            part, m, (m + interval '1 month')::date);
        RETURN part;
    END $$
    """,
    "SELECT neml_ensure_telemetry_partition(current_date)",
    "SELECT neml_ensure_telemetry_partition((current_date + interval '1 month')::date)",
    # ============ SAFETY & AUDIT ============
    """
    CREATE TABLE approvals (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        level           INT NOT NULL CHECK (level BETWEEN 1 AND 4),
        subject_kind    TEXT NOT NULL,
        subject_id      TEXT NOT NULL,
        payload         JSONB NOT NULL,
        requested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
        expires_at      TIMESTAMPTZ NOT NULL,
        decided_at      TIMESTAMPTZ,
        decided_by      TEXT,
        decision        TEXT CHECK (decision IN ('approved','rejected','expired')),
        note            TEXT
    )
    """,
    """
    CREATE TABLE safety_checks (
        id              BIGSERIAL PRIMARY KEY,
        robot_id        TEXT NOT NULL REFERENCES robots(id),
        estop_ok        BOOLEAN NOT NULL,
        watchdog_ok     BOOLEAN NOT NULL,
        current_limit_ok BOOLEAN NOT NULL,
        performed_by    TEXT NOT NULL,
        performed_at    TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE audit_log (
        id              BIGSERIAL PRIMARY KEY,
        ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
        actor           TEXT NOT NULL,
        action          TEXT NOT NULL,
        target          TEXT,
        params_hash     TEXT,
        outcome         TEXT,
        duration_ms     INT,
        approval_id     UUID REFERENCES approvals(id)
    )
    """,
    "CREATE INDEX audit_log_ts_idx ON audit_log (ts DESC)",
    # ============ MEMORY (pgvector) ============
    """
    CREATE TABLE memory_chunks (
        id              BIGSERIAL PRIMARY KEY,
        source_kind     TEXT NOT NULL,
        source_id       TEXT,
        content         TEXT NOT NULL,
        embedding       vector(384) NOT NULL,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX memory_chunks_embedding_idx ON memory_chunks "
    "USING hnsw (embedding vector_cosine_ops)",
    # ============ neml_cloud ONLY ============
    """
    CREATE TABLE users (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        email           TEXT NOT NULL UNIQUE,
        password_hash   TEXT NOT NULL,
        role            TEXT NOT NULL CHECK (role IN ('owner','operator','viewer')),
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE devices (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id         UUID NOT NULL REFERENCES users(id),
        platform        TEXT NOT NULL CHECK (platform IN ('android','ios','web')),
        push_token      TEXT,
        last_seen       TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE commands (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id         UUID NOT NULL REFERENCES users(id),
        idempotency_key TEXT NOT NULL UNIQUE,
        seq             BIGSERIAL,
        kind            TEXT NOT NULL,
        payload         JSONB NOT NULL,
        state           TEXT NOT NULL CHECK (state IN
                          ('pending','delivered','applied','failed','rejected')),
        result          JSONB,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        applied_at      TIMESTAMPTZ
    )
    """,
    "CREATE INDEX commands_state_seq_idx ON commands (state, seq)",
]

# Reverse dependency order.
DROP_ORDER = [
    "commands",
    "devices",
    "users",
    "memory_chunks",
    "audit_log",
    "safety_checks",
    "approvals",
    "telemetry",
    "bom_items",
    "print_jobs",
    "artifacts",
    "sim_runs",
    "candidates",
    "campaigns",
    "task_runs",
    "tasks",
    "skill_validations",
    "skills",
    "robots",
    "genomes",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS neml_ensure_telemetry_partition(date)")
    for table in DROP_ORDER:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
