# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Independent outcome verifier keys and signed robot learning reports."""

from __future__ import annotations

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | None = None
depends_on: str | None = None

TABLES = ("platform_verifiers", "platform_feedback_reports")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE platform_verifiers (
            tenant_id TEXT NOT NULL, domain_id TEXT NOT NULL,
            id TEXT NOT NULL, public_key BYTEA NOT NULL,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            PRIMARY KEY (tenant_id, domain_id, id),
            FOREIGN KEY (tenant_id, domain_id)
              REFERENCES platform_domains(tenant_id, id),
            CHECK (octet_length(public_key) = 32)
        )
    """)
    op.execute("""
        CREATE TABLE platform_feedback_reports (
            tenant_id TEXT NOT NULL, domain_id TEXT NOT NULL,
            report_id UUID NOT NULL, robot_id TEXT NOT NULL,
            operation TEXT NOT NULL, occurred_at TIMESTAMPTZ NOT NULL,
            payload JSONB NOT NULL, payload_sha256 TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, domain_id, report_id),
            FOREIGN KEY (tenant_id, domain_id, robot_id)
              REFERENCES platform_units(tenant_id, domain_id, id),
            CHECK (length(payload_sha256) = 64)
        )
    """)
    op.execute("""
        CREATE INDEX platform_feedback_export_idx
        ON platform_feedback_reports (tenant_id, domain_id, operation, report_id)
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
