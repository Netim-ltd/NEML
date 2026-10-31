# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 14.2 priority formula against a hand-computed table.

P = 100*is_human + 40*urgency + 25*expected_gain + 15*staleness
  + 10*cheapness - 50*blocked

This is arithmetic the whole queue depends on; it must not drift.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from neml_brain.autonomy.discovery import (
    STALENESS_DAYS,
    TaskProposal,
    deadline_urgency,
    order_queue,
    priority,
    staleness_of,
)

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)

# (kwargs, hand-computed P)
TABLE = [
    # nothing scores anything
    ({}, 0.0),
    # every factor maxed, nothing blocked: 100+40+25+15+10
    (
        {
            "is_human": True,
            "urgency": 1.0,
            "expected_gain": 1.0,
            "staleness": 1.0,
            "cheapness": 1.0,
        },
        190.0,
    ),
    # human, deadline right now: 100 + 40*1
    ({"is_human": True, "urgency": 1.0}, 140.0),
    # human waiting on an approval: 100 + 40*0.5 - 50
    ({"is_human": True, "urgency": 0.5, "blocked": True}, 70.0),
    # repair: 25*0.6 + 15*0.5 + 10*0.8 = 15 + 7.5 + 8
    ({"expected_gain": 0.6, "staleness": 0.5, "cheapness": 0.8}, 30.5),
    # exploration, never tried: 25*0.3 + 15*1 + 10*0.9 = 7.5 + 15 + 9
    ({"expected_gain": 0.3, "staleness": 1.0, "cheapness": 0.9}, 31.5),
    # maintenance, hardware fault: 40*1 + 25*0.4 + 15*1 + 10*0.5 = 40 + 10 + 15 + 5
    ({"urgency": 1.0, "expected_gain": 0.4, "staleness": 1.0, "cheapness": 0.5}, 70.0),
    # blocked evolution goes negative: 25*0.5 + 10*0.6 - 50 = 12.5 + 6 - 50
    ({"expected_gain": 0.5, "cheapness": 0.6, "blocked": True}, -31.5),
    # the -50 term alone
    ({"blocked": True}, -50.0),
    # out-of-range factors are clipped to [0,1] before weighting
    ({"urgency": 2.0, "staleness": -1.0}, 40.0),
    # a non-human urgent task can never outrank an idle human one: 40 < 100
    ({"urgency": 1.0, "expected_gain": 1.0, "staleness": 1.0, "cheapness": 1.0}, 90.0),
]


@pytest.mark.parametrize(("kwargs", "expected"), TABLE)
def test_priority_formula(kwargs, expected):
    assert priority(**kwargs) == expected


def test_human_always_outranks_everything_else():
    best_auto = priority(urgency=1.0, expected_gain=1.0, staleness=1.0, cheapness=1.0)
    worst_human = priority(is_human=True)
    assert worst_human > best_auto


def test_staleness_is_days_over_fourteen_clipped():
    assert staleness_of(None, NOW) == 1.0
    assert staleness_of(NOW, NOW) == 0.0
    assert staleness_of(NOW - timedelta(days=7), NOW) == pytest.approx(0.5)
    assert staleness_of(NOW - timedelta(days=STALENESS_DAYS), NOW) == 1.0
    assert staleness_of(NOW - timedelta(days=90), NOW) == 1.0


def test_deadline_urgency_ramps_over_the_last_day():
    assert deadline_urgency(None, NOW) == 0.0
    assert deadline_urgency(NOW + timedelta(hours=24), NOW) == 0.0
    assert deadline_urgency(NOW + timedelta(hours=12), NOW) == pytest.approx(0.5)
    assert deadline_urgency(NOW - timedelta(hours=1), NOW) == 1.0


def _p(name: str, p: float, offset_s: int) -> TaskProposal:
    return TaskProposal(
        title=name,
        kind="exploration",
        source="test",
        priority=p,
        spec={},
        dedupe_key=name,
        created_at=NOW + timedelta(seconds=offset_s),
    )


def test_queue_orders_by_priority_desc_then_created_at_asc():
    proposals = [
        _p("c", 10.0, 0),
        _p("a", 90.0, 30),
        _p("b", 90.0, 10),  # same P, created earlier -> ahead of "a"
        _p("d", -50.0, 5),
    ]
    assert [p.title for p in order_queue(proposals)] == ["b", "a", "c", "d"]
