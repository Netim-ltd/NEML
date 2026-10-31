# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Durable outbound queue (SPEC 9.5): SQLite at NEML_OUTBOX_DB, FIFO, 500 MB cap.

The lab runs fully offline: every message is written here first and drained in
seq order when the link returns. When the cap is hit only `telemetry` is
evicted (Priority.DROPPABLE); events, acks, state, approvals and logs are never
dropped and may push the file past the cap rather than be lost.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .protocol import Envelope, Priority, priority_of

MAX_BYTES = 500 * 1024 * 1024  # SPEC 9.5
DEFAULT_PATH = "/var/lib/neml/outbox.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox (
    seq        INTEGER PRIMARY KEY,
    type       TEXT    NOT NULL,
    priority   INTEGER NOT NULL,
    body       TEXT    NOT NULL,
    queued_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS outbox_evict ON outbox (priority, seq);
CREATE TABLE IF NOT EXISTS inbound (
    idempotency_key TEXT PRIMARY KEY,
    seen_at         TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v INTEGER NOT NULL);
"""


class Outbox:
    """FIFO durable queue. Also owns the monotonic `seq` and inbound dedupe set.

    ponytail: synchronous sqlite on the event loop. Messages are small and the
    bridge is single-process; move to a thread executor if drain latency ever
    shows up in the metrics.
    """

    def __init__(self, path: str | Path | None = None, *, max_bytes: int = MAX_BYTES) -> None:
        self.path = Path(path or os.environ.get("NEML_OUTBOX_DB", DEFAULT_PATH))
        self.max_bytes = max_bytes
        self.dropped = 0
        if self.path.parent != Path():
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA auto_vacuum=INCREMENTAL")  # deletes must give the disk back
        self._db.executescript(_SCHEMA)
        total = self._db.execute("SELECT COALESCE(SUM(LENGTH(body)),0) FROM outbox").fetchone()
        self._bytes = int(total[0])

    # --- sequence -------------------------------------------------------
    def next_seq(self) -> int:
        """Monotonic across restarts (SPEC 3.1: every message carries seq)."""
        row = self._db.execute(
            "INSERT INTO meta(k,v) VALUES('seq',1) "
            "ON CONFLICT(k) DO UPDATE SET v=meta.v+1 RETURNING v"
        ).fetchone()
        return int(row[0])

    # --- outbound -------------------------------------------------------
    def put(self, env: Envelope) -> None:
        body = env.model_dump_json()
        self._db.execute(
            "INSERT INTO outbox(seq,type,priority,body,queued_at) VALUES(?,?,?,?,?)",
            (env.seq, env.type, int(priority_of(env.type)), body, datetime.now(UTC).isoformat()),
        )
        self._bytes += len(body)
        self._evict()

    def peek(self, limit: int = 100) -> list[Envelope]:
        rows = self._db.execute("SELECT body FROM outbox ORDER BY seq LIMIT ?", (limit,)).fetchall()
        return [Envelope.model_validate_json(r[0]) for r in rows]

    def ack(self, seq: int) -> None:
        """Delete one delivered message. Un-acked rows are resent after reconnect."""
        row = self._db.execute("SELECT LENGTH(body) FROM outbox WHERE seq=?", (seq,)).fetchone()
        if row is None:
            return
        self._db.execute("DELETE FROM outbox WHERE seq=?", (seq,))
        self._bytes -= int(row[0])

    def pending(self) -> int:
        return int(self._db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0])

    @property
    def nbytes(self) -> int:
        return self._bytes

    def _evict(self) -> None:
        while self._bytes > self.max_bytes:
            row = self._db.execute(
                "SELECT seq, LENGTH(body) FROM outbox WHERE priority=? ORDER BY seq LIMIT 1",
                (int(Priority.DROPPABLE),),
            ).fetchone()
            if row is None:
                return  # only durable messages left - SPEC 9.5 forbids dropping them
            self._db.execute("DELETE FROM outbox WHERE seq=?", (row[0],))
            self._bytes -= int(row[1])
            self.dropped += 1
        self._db.execute("PRAGMA incremental_vacuum")

    # --- inbound dedupe -------------------------------------------------
    def claim(self, idempotency_key: str) -> bool:
        """True the first time this key is seen; False for a replay (SPEC 3.1)."""
        cur = self._db.execute(
            "INSERT OR IGNORE INTO inbound(idempotency_key,seen_at) VALUES(?,?)",
            (idempotency_key, datetime.now(UTC).isoformat()),
        )
        return cur.rowcount == 1

    def close(self) -> None:
        self._db.close()
