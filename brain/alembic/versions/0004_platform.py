# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tenant-scoped platform ledger and training data with database row security."""

from __future__ import annotations

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None

TABLES = (
    "platform_domains",
    "platform_units",
    "platform_events",
    "platform_episodes",
    "platform_models",
    "platform_deployments",
    "platform_deployment_targets",
    "platform_gaps",
    "platform_outbox",
)


def upgrade() -> None:
    op.execute("CREATE TABLE platform_tenants (id TEXT PRIMARY KEY, name TEXT NOT NULL)")
    op.execute("""
        CREATE TABLE platform_domains (
            tenant_id TEXT NOT NULL REFERENCES platform_tenants(id),
            id TEXT NOT NULL, name TEXT NOT NULL,
            PRIMARY KEY (tenant_id, id)
        )
    """)
    op.execute("""
        CREATE TABLE platform_units (
            tenant_id TEXT NOT NULL, domain_id TEXT NOT NULL, id TEXT NOT NULL,
            rank SMALLINT NOT NULL CHECK (rank BETWEEN 0 AND 3),
            parent_id TEXT, robot_type TEXT, device_public_key BYTEA,
            safe_default TEXT NOT NULL,
            CHECK ((rank = 3 AND robot_type IS NOT NULL) OR
                   (rank < 3 AND robot_type IS NULL)),
            PRIMARY KEY (tenant_id, domain_id, id),
            FOREIGN KEY (tenant_id, domain_id)
              REFERENCES platform_domains(tenant_id, id),
            FOREIGN KEY (tenant_id, domain_id, parent_id)
              REFERENCES platform_units(tenant_id, domain_id, id)
        )
    """)
    op.execute("""
        CREATE TABLE platform_events (
            tenant_id TEXT NOT NULL, domain_id TEXT NOT NULL, id TEXT NOT NULL,
            kind TEXT NOT NULL, subject_id TEXT NOT NULL,
            schema_version INTEGER NOT NULL CHECK (schema_version > 0),
            occurred_at TIMESTAMPTZ NOT NULL, payload JSONB NOT NULL,
            PRIMARY KEY (tenant_id, domain_id, id),
            FOREIGN KEY (tenant_id, domain_id)
              REFERENCES platform_domains(tenant_id, id)
        )
    """)
    op.execute(
        "CREATE INDEX platform_events_subject_idx ON platform_events "
        "(tenant_id, domain_id, subject_id, occurred_at DESC)"
    )
    op.execute("""
        CREATE TABLE platform_episodes (
            tenant_id TEXT NOT NULL, domain_id TEXT NOT NULL, id TEXT NOT NULL,
            robot_type TEXT NOT NULL, robot_id TEXT NOT NULL,
            model_version TEXT NOT NULL,
            observed_at TIMESTAMPTZ NOT NULL,
            observation_hash TEXT NOT NULL, action TEXT NOT NULL,
            outcome TEXT NOT NULL, reward DOUBLE PRECISION NOT NULL,
            failure_class TEXT, quality DOUBLE PRECISION NOT NULL,
            features JSONB NOT NULL,
            CHECK (reward BETWEEN -1 AND 1), CHECK (quality BETWEEN 0 AND 1),
            PRIMARY KEY (tenant_id, domain_id, id),
            FOREIGN KEY (tenant_id, domain_id)
              REFERENCES platform_domains(tenant_id, id)
        )
    """)
    op.execute(
        "CREATE INDEX platform_episodes_training_idx ON platform_episodes "
        "(tenant_id, domain_id, robot_type, observed_at DESC)"
    )
    op.execute("""
        CREATE TABLE platform_models (
            tenant_id TEXT NOT NULL, domain_id TEXT NOT NULL,
            robot_type TEXT NOT NULL, version TEXT NOT NULL,
            artifact_path TEXT NOT NULL, artifact_sha256 TEXT NOT NULL,
            signature TEXT NOT NULL, training_start TIMESTAMPTZ NOT NULL,
            training_end TIMESTAMPTZ NOT NULL, metrics JSONB NOT NULL,
            rollback_version TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, domain_id, robot_type, version),
            FOREIGN KEY (tenant_id, domain_id)
              REFERENCES platform_domains(tenant_id, id)
        )
    """)
    op.execute("""
        CREATE TABLE platform_deployments (
            tenant_id TEXT NOT NULL, domain_id TEXT NOT NULL,
            robot_type TEXT NOT NULL, candidate_version TEXT NOT NULL,
            previous_version TEXT NOT NULL, stage TEXT NOT NULL,
            canary_approval_id UUID, fleet_approval_id UUID,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, domain_id, robot_type, candidate_version),
            FOREIGN KEY (tenant_id, domain_id, robot_type, candidate_version)
              REFERENCES platform_models(tenant_id, domain_id, robot_type, version)
        )
    """)
    op.execute("""
        CREATE TABLE platform_gaps (
            tenant_id TEXT NOT NULL, domain_id TEXT NOT NULL, task_id TEXT NOT NULL,
            required JSONB NOT NULL, reason TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'open', created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, domain_id, task_id),
            FOREIGN KEY (tenant_id, domain_id)
              REFERENCES platform_domains(tenant_id, id)
        )
    """)
    op.execute("""
        CREATE TABLE platform_deployment_targets (
            tenant_id TEXT NOT NULL, domain_id TEXT NOT NULL,
            robot_type TEXT NOT NULL, candidate_version TEXT NOT NULL,
            robot_id TEXT NOT NULL, stage TEXT NOT NULL,
            requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            acknowledged_at TIMESTAMPTZ, applied_version TEXT,
            PRIMARY KEY (tenant_id, domain_id, robot_type, candidate_version, robot_id, stage),
            FOREIGN KEY (tenant_id, domain_id, robot_type, candidate_version)
              REFERENCES platform_deployments(tenant_id, domain_id, robot_type, candidate_version),
            FOREIGN KEY (tenant_id, domain_id, robot_id)
              REFERENCES platform_units(tenant_id, domain_id, id)
        )
    """)
    op.execute("""
        CREATE TABLE platform_outbox (
            tenant_id TEXT NOT NULL, domain_id TEXT NOT NULL, event_id TEXT NOT NULL,
            payload JSONB NOT NULL, delivered_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, domain_id, event_id),
            FOREIGN KEY (tenant_id, domain_id, event_id)
              REFERENCES platform_events(tenant_id, domain_id, id)
        )
    """)
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_tenant_policy ON {table}
            USING (tenant_id = current_setting('neml.tenant_id', true))
            WITH CHECK (tenant_id = current_setting('neml.tenant_id', true))
        """)


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE {table}")
    op.execute("DROP TABLE platform_tenants")
