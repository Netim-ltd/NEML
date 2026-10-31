#!/usr/bin/env bash
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# NEML_SPEC.md 7: telemetry is PARTITION BY RANGE (ts); this script runs monthly from a
# systemd timer and makes sure the current and the next month's partitions exist.
# Idempotent: the SQL side is CREATE TABLE IF NOT EXISTS, so running it twice, or running it
# late after a missed month, is safe. Ubuntu 24.04 + postgresql-client.
#
# Usage:  NEML_DB_URL=... scripts/db/create_partitions.sh

set -euo pipefail

DB_URL="${NEML_DB_URL:?NEML_DB_URL is not set (SPEC 17.3)}"
# NEML_DB_URL is a SQLAlchemy URL (postgresql+asyncpg://...); libpq wants it without the driver.
PSQL_URL="${DB_URL/+asyncpg/}"

# 0 = this month (self-heal after a missed run), 1 = next month (the actual job).
for offset in 0 1; do
    part=$(psql "$PSQL_URL" -v ON_ERROR_STOP=1 -qAt \
        -c "SELECT neml_ensure_telemetry_partition((current_date + interval '${offset} month')::date)")
    echo "telemetry partition ready: ${part}"
done
