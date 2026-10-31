# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Owner-entered per-model and lab-wide settings (admin screen) and autonomy tuning."""

from __future__ import annotations

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE model_settings (
            model_id TEXT PRIMARY KEY,
            values JSONB NOT NULL DEFAULT '{}'::jsonb,
            updated_by TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    # One row per task kind: the factors the SPEC 14.2 priority formula needs and
    # the spec does not give. Refitted from task_runs by autonomy/tuning.py.
    op.execute("""
        CREATE TABLE autonomy_tuning (
            kind TEXT PRIMARY KEY,
            expected_gain DOUBLE PRECISION NOT NULL CHECK (expected_gain BETWEEN 0 AND 1),
            cheapness DOUBLE PRECISION NOT NULL CHECK (cheapness BETWEEN 0 AND 1),
            samples INTEGER NOT NULL DEFAULT 0,
            fitted_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    # Verdict of the outcome judge for each run, kept apart from task_runs.outcome
    # (what the executor claimed) so the two can disagree and be audited.
    op.execute("""
        CREATE TABLE task_verdicts (
            id BIGSERIAL PRIMARY KEY,
            task_run_id BIGINT NOT NULL REFERENCES task_runs(id),
            done BOOLEAN NOT NULL,
            reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
            action TEXT NOT NULL,
            judged_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (task_run_id)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE task_verdicts")
    op.execute("DROP TABLE autonomy_tuning")
    op.execute("DROP TABLE model_settings")
