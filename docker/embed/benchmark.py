# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""T-006 acceptance benchmark: 100 chunks in under 3 seconds, 384 dimensions.

Runs inside the container, against the loaded encoder (no HTTP in the way):

    docker compose -f docker/compose.yml exec embed python benchmark.py

Exit code 0 means the T-006 criterion is met.
"""

from __future__ import annotations

import sys
import time

from app import DIM, Encoder

CHUNKS = 100
BUDGET_S = 3.0
BATCH = 16  # SPEC 4.6 quotes ~40 chunk/s on 8 cores; batching is how you get it


def main() -> int:
    texts = [
        f"passage: NEML kalibrasyon kaydi {i}: referans manevra M{i % 5 + 1}, "
        f"sapma {i * 0.001:.3f} m, enerji {i * 0.07:.2f} Wh, tekrar {i % 10}."
        for i in range(CHUNKS)
    ]
    encoder = Encoder()
    encoder.encode(texts[:BATCH])  # warm up: first run pays for arena allocation

    start = time.perf_counter()
    vectors = [v for i in range(0, CHUNKS, BATCH) for v in encoder.encode(texts[i : i + BATCH])]
    elapsed = time.perf_counter() - start

    dims = {len(v) for v in vectors}
    print(f"{len(vectors)} chunks in {elapsed:.2f} s ({len(vectors) / elapsed:.1f} chunk/s)")
    print(f"dimensions: {dims}")
    if dims != {DIM}:
        print(f"FAIL: expected {DIM} dimensions (SPEC 4.6)", file=sys.stderr)
        return 1
    if elapsed > BUDGET_S:
        print(f"FAIL: {elapsed:.2f} s > {BUDGET_S} s budget (T-006)", file=sys.stderr)
        return 1
    print("OK: T-006 met")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
