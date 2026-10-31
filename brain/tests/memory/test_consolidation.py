# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 14.6 consolidation -- the routine idle policy step 5 calls."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from neml_brain.memory.consolidation import WINDOW_H, consolidate, failure_document

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)

RUNS = [
    {
        "id": 41,
        "env": "sim",
        "seed": 99,
        "metrics": {"failure_tag": "foot_slip", "deviation_m": 0.31},
        "title": "40 mm basamak tirmanma",
        "kind": "repair",
    },
    {
        "id": 42,
        "env": "tethered",
        "seed": 7,
        "metrics": None,
        "title": "duz yurume",
        "kind": "exploration",
    },
]


def test_failure_document_leads_with_the_failure_tag():
    document = failure_document(RUNS[0])
    assert document.startswith("failure_tag: foot_slip")
    assert "40 mm basamak tirmanma" in document
    assert "env: sim seed: 99" in document
    assert "deviation_m=0.31" in document


def test_an_untagged_failure_is_still_recorded():
    assert failure_document(RUNS[1]).startswith("failure_tag: untagged")


async def test_consolidation_chunks_embeds_and_stores(session, embedder):
    session.rows = RUNS
    written = await consolidate(session, embedder, now=NOW)

    assert written == 2  # one chunk per short failure document
    select_sql, select_params = session.calls[0]
    assert select_params["since"] == NOW - timedelta(hours=WINDOW_H)
    assert "tr.outcome = 'failure'" in select_sql
    assert "NOT EXISTS" in select_sql  # never consolidate the same run twice

    insert_params = session.calls[-1][1]
    assert [row["source_id"] for row in insert_params] == ["task_run:41", "task_run:42"]
    assert all(row["source_kind"] == "failure" for row in insert_params)
    assert all(row["embedding"].startswith("[") for row in insert_params)

    texts, kind = embedder.seen[-1]
    assert kind == "passage"
    assert len(texts) == 2


async def test_nothing_to_consolidate_is_not_an_error(session, embedder):
    session.rows = []
    assert await consolidate(session, embedder, now=NOW) == 0
    assert len(session.calls) == 1  # only the SELECT
    assert embedder.seen == []


async def test_the_window_is_twenty_four_hours(session, embedder):
    assert WINDOW_H == 24
    await consolidate(session, embedder, now=NOW)
    assert session.calls[0][1]["since"] == NOW - timedelta(hours=24)
