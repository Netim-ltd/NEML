# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# skill_runs + budget_usage (ADR-011, owner decision amending SPEC 7)
#
# SPEC 14.2 / 14.6 count "a skill's last 20 runs" and SPEC 14.4 keeps daily budget counters;
# SPEC 7 had a row for neither. Raw SQL for the same reason as 0001: the approved DDL is the
# contract, so op.create_table() would only add a place for it to drift.
#
# Revision ID: 0003
# Revises: 0002
# Create Date: 2026-09-16

from __future__ import annotations

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


STATEMENTS: list[str] = [
    """
    CREATE TABLE skill_runs (
        id              BIGSERIAL PRIMARY KEY,
        skill_id        TEXT NOT NULL REFERENCES skills(id),
        task_run_id     BIGINT REFERENCES task_runs(id),
        env             TEXT NOT NULL CHECK (env IN ('sim','real')),
        seed            BIGINT,
        success         BOOLEAN NOT NULL,
        failure_mode    TEXT,
        deterministic   BOOLEAN NOT NULL DEFAULT TRUE,
        run_at          TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # The approved DDL leaves this index unnamed; the name below is the one PostgreSQL would
    # pick anyway, spelled out so downgrade and the metadata test have something to hold.
    "CREATE INDEX skill_runs_skill_id_run_at_idx ON skill_runs (skill_id, run_at DESC)",
    """
    CREATE TABLE budget_usage (
        day             DATE NOT NULL,
        resource        TEXT NOT NULL,
        used            NUMERIC(14,4) NOT NULL DEFAULT 0,
        PRIMARY KEY (day, resource)
    )
    """,
]

# Reverse dependency order.
DROP_ORDER = ["budget_usage", "skill_runs"]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for table in DROP_ORDER:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
