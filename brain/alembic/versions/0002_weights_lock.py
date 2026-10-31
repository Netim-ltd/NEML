# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# campaigns.weights immutability trigger (SPEC 14.3, acceptance criterion of T-090)
#
# SPEC 14.3: "the weights are fixed at the start of the campaign, written to campaigns.weights
# and cannot be changed for the lifetime of the campaign (protected by a DB trigger)". Changing
# the weights after seeing the result invalidates the result, so there is deliberately NO
# escape hatch -- not `state <> 'active'`, not stopped, not completed. Any UPDATE that touches
# weights raises. A campaign that needs different weights is a new campaign row.
#
# Revision ID: 0002
# Revises: 0001
# Create Date: 2026-02-10

from __future__ import annotations

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


TRIGGER_FN = """
CREATE OR REPLACE FUNCTION neml_campaigns_weights_locked()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.weights IS DISTINCT FROM OLD.weights THEN
        RAISE EXCEPTION
            'campaigns.weights is immutable once the campaign exists (SPEC 14.3): campaign %',
            OLD.id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END $$
"""

TRIGGER = """
CREATE TRIGGER campaigns_weights_lock
BEFORE UPDATE ON campaigns
FOR EACH ROW
EXECUTE FUNCTION neml_campaigns_weights_locked()
"""


def upgrade() -> None:
    op.execute(TRIGGER_FN)
    op.execute(TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS campaigns_weights_lock ON campaigns")
    op.execute("DROP FUNCTION IF EXISTS neml_campaigns_weights_locked()")
