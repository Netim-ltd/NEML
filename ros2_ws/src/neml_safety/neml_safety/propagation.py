# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Propagation budget accounting for T-074: an e-stop event reaches the whole
stack in under 50 ms.

The criterion is a number, so it has to be measured, not asserted in a comment.
This module is the measuring stick: a trace is opened with a monotonic
timestamp the instant the e-stop enters the process, every hop after it stamps
itself, and the total is compared against the budget. The node uses it in
production (it logs when a real event blows the budget) and the tests use it
with injected timestamps, so the arithmetic is covered without waiting for real
milliseconds or owning a robot.

WHY A MONOTONIC CLOCK AND NOT THE ROS CLOCK
    The ROS clock is the sim clock when use_sim_time is on, and a latency
    figure that can be produced by a fast simulation is worthless. A safety
    number has to come from a clock nothing in this system can wind. That is
    also why the node keeps using its ROS clock for the latch state machine and
    this clock only for the budget: the two are answering different questions.

ponytail: CLOCK_MONOTONIC is host-wide, so hop timestamps compare directly
between processes on one robot - which is where the whole T-074 chain runs.
Across two robots they do not compare at all, and nothing here pretends
otherwise; a cross-robot number needs the ROS header stamp and a synchronised
clock, and it is not what T-074 asks for.
"""

import time
from dataclasses import dataclass

# NEML_SPEC.md SS16 T-074. Not a tunable.
ESTOP_BUDGET_MS = 50.0


def now_ns() -> int:
    """The one clock the budget is measured on."""
    return time.monotonic_ns()


@dataclass(frozen=True)
class Hop:
    """One point the event passed through."""

    name: str
    at_ns: int


class Trace:
    """An e-stop event on its way through the stack.

    Opened at ingress - the moment the e-stop first became knowable to
    software - and stamped by each hop after it. Every number it reports is
    measured from ingress, because that is what the 50 ms is measured from.
    """

    def __init__(self, ingress_ns: int, label: str = "estop") -> None:
        self.label = label
        self.ingress_ns = ingress_ns
        self._hops: list[Hop] = []

    def record(self, name: str, at_ns: int | None = None) -> Hop:
        """Stamp a hop. Defaults to right now, which is what a subscriber does.

        Time going backwards is rejected rather than reported as a negative
        latency: on one host it cannot happen with a monotonic clock, so if it
        does the caller has mixed two clocks and the number is a lie.
        """
        hop = Hop(name, now_ns() if at_ns is None else at_ns)
        previous = self._hops[-1].at_ns if self._hops else self.ingress_ns
        if hop.at_ns < previous:
            raise ValueError(f"hop {name!r} is earlier than the hop before it")
        self._hops.append(hop)
        return hop

    @property
    def hops(self) -> tuple[Hop, ...]:
        return tuple(self._hops)

    @property
    def total_ms(self) -> float:
        """Ingress to the last hop. Zero while nothing has been stamped."""
        if not self._hops:
            return 0.0
        return (self._hops[-1].at_ns - self.ingress_ns) / 1e6

    def elapsed_ms(self, name: str) -> float:
        """Ingress to the named hop."""
        for hop in self._hops:
            if hop.name == name:
                return (hop.at_ns - self.ingress_ns) / 1e6
        raise KeyError(name)

    def breakdown(self) -> list[tuple[str, float]]:
        """Per-hop cost in ms, in order. This is what you read when the budget
        is blown: it names the hop that ate it."""
        out: list[tuple[str, float]] = []
        previous = self.ingress_ns
        for hop in self._hops:
            out.append((hop.name, (hop.at_ns - previous) / 1e6))
            previous = hop.at_ns
        return out

    def over_budget(self, budget_ms: float = ESTOP_BUDGET_MS) -> bool:
        return self.total_ms > budget_ms

    def report(self, budget_ms: float = ESTOP_BUDGET_MS) -> str:
        """One log line. Deliberately printable: the T-075 acceptance test is a
        human reading the journal next to an oscilloscope."""
        parts = " ".join(f"{name}={ms:.3f}ms" for name, ms in self.breakdown())
        verdict = "OVER BUDGET" if self.over_budget(budget_ms) else "ok"
        return (
            f"{self.label}: {self.total_ms:.3f} ms / {budget_ms:.0f} ms {verdict} [{parts}]"
        )
