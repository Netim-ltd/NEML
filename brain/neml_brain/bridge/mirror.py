# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lab -> cloud mirror of the rows the app reads: genomes, campaigns, tasks, candidates, runs.

The cloud API has its own database (neml_cloud) and the app only ever reads that one. Without
this the web panel and the phone app show an empty lab however busy it is. Rows travel as the
`MirrorRows` event (SPEC 9.5 keeps the six message types; this is one more named event on the
`event` type) and the cloud upserts them by primary key.

Polling and a content hash per row, like bridge/live.py: it covers rows written by any process,
sends only what changed, and every ten minutes forgets what it sent so a batch the cloud could
not apply (a child that beat its parent) is repaired by the next pass.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

BATCH = 100
RESEND_AFTER_S = 600

# Parents first: a candidate needs its genome and campaign, a run needs its task.
QUERIES: tuple[tuple[str, str], ...] = (
    ("genomes", "SELECT to_jsonb(g) AS row FROM genomes g ORDER BY g.created_at, g.version"),
    ("campaigns", "SELECT to_jsonb(c) AS row FROM campaigns c ORDER BY c.started_at"),
    (
        "tasks",
        "SELECT to_jsonb(t) AS row FROM tasks t WHERE t.updated_at > now() - interval '7 days'"
        " ORDER BY t.created_at",
    ),
    (
        "candidates",
        "SELECT to_jsonb(k) AS row FROM candidates k WHERE k.campaign_id IN ("
        " SELECT id FROM campaigns"
        " WHERE state = 'active' OR coalesce(ended_at, now()) > now() - interval '7 days')"
        " ORDER BY k.created_at",
    ),
    (
        "task_runs",
        "SELECT to_jsonb(r) AS row FROM task_runs r WHERE r.started_at > now() - interval '7 days'"
        " ORDER BY r.id",
    ),
)


class MirrorPublisher:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        send: Callable[..., Any],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sessions, self._send, self._clock = sessions, send, clock
        self._sent: dict[tuple[str, str], str] = {}
        self._cleared_at = clock()

    async def publish(self) -> int:
        """Send every row that changed since the last pass. Returns how many."""
        if self._clock() - self._cleared_at > RESEND_AFTER_S:
            self._sent.clear()
            self._cleared_at = self._clock()
        total = 0
        for table, sql in QUERIES:
            async with self._sessions() as session:
                rows = [r.row for r in (await session.execute(sa.text(sql))).all()]
            changed = []
            for row in rows:
                digest = hashlib.sha1(  # noqa: S324 - change detection, not security
                    json.dumps(row, sort_keys=True, default=str).encode()
                ).hexdigest()
                key = (table, str(row["id"]))
                if self._sent.get(key) != digest:
                    self._sent[key] = digest
                    changed.append(row)
            for start in range(0, len(changed), BATCH):
                self._send(
                    "event",
                    {
                        "name": "MirrorRows",
                        "data": {"table": table, "rows": changed[start : start + BATCH]},
                    },
                )
            total += len(changed)
        return total
