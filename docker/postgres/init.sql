-- Copyright (c) 2026 Mustafa Gulsoy.
-- SPDX-License-Identifier: AGPL-3.0-or-later
--
-- NEML_SPEC.md 7 - runs once, on an empty data directory, before Alembic.
-- Alembic owns the tables (T-003); this file owns only what a migration cannot
-- do: the extensions and the server settings.

CREATE EXTENSION IF NOT EXISTS vector;    -- SPEC 7 / 4.6: vector(384) + HNSW
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- SPEC 7: gen_random_uuid()

-- Workload (SPEC 7): telemetry inserted at 1 Hz per robot into a RANGE
-- partitioned table, HNSW index builds over memory_chunks, and analytical reads
-- over runs/sim_runs. ALTER SYSTEM writes postgresql.auto.conf; the init phase
-- ends with a restart, so even shared_buffers takes effect.
-- ponytail: sized for the 16 GB lab box of SPEC 3. On different hardware change
-- these four numbers and restart; nothing else in the tree depends on them.
ALTER SYSTEM SET shared_buffers = '2GB';
ALTER SYSTEM SET effective_cache_size = '6GB';
ALTER SYSTEM SET work_mem = '32MB';
ALTER SYSTEM SET maintenance_work_mem = '1GB';   -- HNSW build is the consumer

ALTER SYSTEM SET random_page_cost = 1.1;         -- NVMe, not a spinning disk
ALTER SYSTEM SET effective_io_concurrency = 200;
ALTER SYSTEM SET max_parallel_maintenance_workers = 2;  -- parallel HNSW build
ALTER SYSTEM SET max_worker_processes = 8;
ALTER SYSTEM SET max_parallel_workers = 4;

-- Partition pruning and per-partition planning for `telemetry` (SPEC 7).
ALTER SYSTEM SET enable_partitionwise_aggregate = on;
ALTER SYSTEM SET enable_partitionwise_join = on;

-- The whole system is UTC; TRT only exists in the budget reset (SPEC 14.4).
ALTER SYSTEM SET timezone = 'UTC';

-- Long-lived async connections from the brain; keep dead ones from piling up.
ALTER SYSTEM SET idle_in_transaction_session_timeout = '60s';
ALTER SYSTEM SET tcp_keepalives_idle = 60;
