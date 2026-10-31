# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 9.5 outbox: FIFO, monotonic seq, 500 MB cap, telemetry-only eviction."""

from __future__ import annotations

from neml_brain.bridge.outbox import MAX_BYTES, Outbox
from neml_brain.bridge.protocol import new_envelope


def _outbox(tmp_path, **kw) -> Outbox:
    return Outbox(tmp_path / "outbox.db", **kw)


def test_cap_is_the_spec_value():
    assert MAX_BYTES == 500 * 1024 * 1024


def test_fifo_order_and_ack(tmp_path):
    box = _outbox(tmp_path)
    seqs = [box.next_seq() for _ in range(3)]
    for s in seqs:
        box.put(new_envelope(s, "event", {"n": s}))
    assert [e.seq for e in box.peek()] == seqs
    box.ack(seqs[0])
    assert [e.seq for e in box.peek()] == seqs[1:]
    assert box.pending() == 2
    box.close()


def test_seq_is_monotonic_across_reopen(tmp_path):
    box = _outbox(tmp_path)
    first = [box.next_seq() for _ in range(3)]
    box.close()
    box = _outbox(tmp_path)
    second = [box.next_seq() for _ in range(3)]
    box.close()
    assert first == [1, 2, 3]
    assert second == [4, 5, 6]


def test_survives_offline_and_drains_in_order(tmp_path):
    """The lab works fully offline: nothing is sent, nothing is lost."""
    box = _outbox(tmp_path)
    for _ in range(50):
        s = box.next_seq()
        box.put(new_envelope(s, "telemetry", {"v": s}))
    box.close()
    box = _outbox(tmp_path)
    drained = box.peek(limit=1000)
    assert len(drained) == 50
    assert [e.seq for e in drained] == sorted(e.seq for e in drained)
    box.close()


def test_overflow_drops_oldest_telemetry_and_keeps_events(tmp_path):
    """Forced overflow with a shrunken cap - SPEC 9.5 asymmetry."""
    box = _outbox(tmp_path, max_bytes=4096)
    blob = "x" * 200
    telemetry_seqs, event_seqs = [], []
    for i in range(80):
        s = box.next_seq()
        if i % 2:
            event_seqs.append(s)
            box.put(new_envelope(s, "event", {"blob": blob}))
        else:
            telemetry_seqs.append(s)
            box.put(new_envelope(s, "telemetry", {"blob": blob}))

    remaining = {e.seq for e in box.peek(limit=1000)}
    assert event_seqs and set(event_seqs) <= remaining, "events must never be dropped"
    assert box.dropped > 0
    kept_telemetry = [s for s in telemetry_seqs if s in remaining]
    assert len(kept_telemetry) < len(telemetry_seqs), "telemetry must be dropped"
    # the survivors are the newest telemetry: eviction is oldest-first
    assert kept_telemetry == telemetry_seqs[len(telemetry_seqs) - len(kept_telemetry) :]
    box.close()


def test_durable_only_queue_is_never_evicted(tmp_path):
    """No telemetry to sacrifice means the cap yields, not the data."""
    box = _outbox(tmp_path, max_bytes=512)
    seqs = []
    for _ in range(20):
        s = box.next_seq()
        seqs.append(s)
        box.put(new_envelope(s, "command_ack", {"blob": "y" * 200}))
    assert [e.seq for e in box.peek(limit=100)] == seqs
    assert box.dropped == 0
    assert box.nbytes > box.max_bytes
    box.close()


def test_claim_is_idempotent(tmp_path):
    box = _outbox(tmp_path)
    assert box.claim("abc") is True
    assert box.claim("abc") is False
    box.close()
    box = _outbox(tmp_path)
    assert box.claim("abc") is False, "dedupe must survive a restart"
    box.close()
