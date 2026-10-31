# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Chunking for memory_chunks."""

from __future__ import annotations

import pytest

from neml_brain.memory.chunking import CHUNK_CHARS, CHUNK_OVERLAP, chunk_text

WORDS = ("basamak", "tork", "sapma", "enerji", "kalibrasyon", "gecikme")
LONG = " ".join(WORDS[i % len(WORDS)] for i in range(600))


def test_empty_input_yields_nothing():
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


def test_short_text_is_one_chunk():
    assert chunk_text("tek parca kayit") == ["tek parca kayit"]


def test_long_text_is_split_into_bounded_chunks():
    chunks = chunk_text(LONG)
    assert len(chunks) > 1
    assert all(len(c) <= CHUNK_CHARS for c in chunks)
    assert all(c == c.strip() for c in chunks)


def test_chunks_never_split_a_word():
    for chunk in chunk_text(LONG):
        for token in chunk.split():
            assert token in WORDS


def test_chunks_cover_the_whole_text():
    rebuilt = " ".join(chunk_text(LONG, size=200, overlap=0))
    assert rebuilt.split() == LONG.split()


def test_consecutive_chunks_overlap():
    chunks = chunk_text(LONG, size=300, overlap=60)
    assert sum(len(c) for c in chunks) > len(LONG)  # the overlap duplicates text
    tail = " ".join(chunks[0].split()[-3:])
    assert tail in chunks[1]


def test_bad_parameters_are_refused():
    with pytest.raises(ValueError, match="chunk size"):
        chunk_text("x", size=0)
    with pytest.raises(ValueError, match="overlap"):
        chunk_text("x", size=100, overlap=100)
    assert CHUNK_OVERLAP < CHUNK_CHARS
