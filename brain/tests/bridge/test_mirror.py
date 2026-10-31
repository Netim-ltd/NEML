# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""MirrorPublisher: parents first, only what changed, and a periodic full resend."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from neml_brain.bridge.mirror import BATCH, QUERIES, RESEND_AFTER_S, MirrorPublisher


class FakeSessions:
    def __init__(self, tables: dict[str, list[dict[str, Any]]]) -> None:
        self.tables = tables

    def __call__(self) -> FakeSessions:
        return self

    async def __aenter__(self) -> FakeSessions:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def execute(self, statement: Any) -> Any:
        sql = str(statement)
        table = next(name for name, query in QUERIES if query == sql)
        return SimpleNamespace(all=lambda: [SimpleNamespace(row=r) for r in self.tables[table]])


def publisher(
    tables: dict[str, list[dict[str, Any]]],
) -> tuple[MirrorPublisher, list[Any], list[float]]:
    sent: list[Any] = []
    now = [0.0]
    pub = MirrorPublisher(
        FakeSessions(tables),  # type: ignore[arg-type]
        lambda kind, payload: sent.append((kind, payload)),
        clock=lambda: now[0],
    )
    return pub, sent, now


def tables(**rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {name: rows.get(name, []) for name, _ in QUERIES}


async def test_parents_are_sent_before_the_rows_that_reference_them() -> None:
    pub, sent, _ = publisher(
        tables(
            genomes=[{"id": "g1"}],
            campaigns=[{"id": "c1"}],
            candidates=[{"id": "k1", "genome_id": "g1"}],
        )
    )
    assert await pub.publish() == 3
    assert [p["data"]["table"] for _, p in sent] == ["genomes", "campaigns", "candidates"]
    assert all(kind == "event" and p["name"] == "MirrorRows" for kind, p in sent)


async def test_an_unchanged_row_is_not_sent_again_but_a_changed_one_is() -> None:
    data = tables(tasks=[{"id": "t1", "state": "queued"}])
    pub, sent, _ = publisher(data)
    assert await pub.publish() == 1
    assert await pub.publish() == 0
    data["tasks"][0]["state"] = "running"
    assert await pub.publish() == 1
    assert len(sent) == 2


async def test_batches_are_capped_and_a_full_resend_happens_after_ten_minutes() -> None:
    data = tables(tasks=[{"id": f"t{i}"} for i in range(BATCH + 5)])
    pub, sent, now = publisher(data)
    await pub.publish()
    assert [len(p["data"]["rows"]) for _, p in sent] == [BATCH, 5]
    now[0] = RESEND_AFTER_S + 1
    assert await pub.publish() == BATCH + 5  # the cloud may have dropped a batch: send it all
