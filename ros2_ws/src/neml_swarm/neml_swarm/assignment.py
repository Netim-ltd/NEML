# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Pure swarm coordination logic (NEML_SPEC.md Faz 5, T-082 and T-083).

Everything here is a function of (state, now). No clock, no ROS, no network,
so the failover behaviour is testable in milliseconds instead of by unplugging
a robot.

Split of duties: lease.py decides WHETHER a task is up for grabs (ownership,
epochs, expiry). This file decides WHO should get it (placement) and when a
robot has to give up on the link (the T-083 timer). The coordinator's plan from
here is advisory; the binding ownership is always the lease.

The placement policy is liveness and load balancing only - it does not look at
battery state, skill capability or deployment level. That arrives with
T-084/T-085 when the autonomy loop owns the task queue.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

# T-083: a robot that has not heard from the coordinator for this long must be
# in a safe state. The guard trips at 80% of it so the transition has finished
# before the deadline rather than starting at it.
LINK_TIMEOUT_S = 2.0
TRIP_FRACTION = 0.8


@dataclass(frozen=True)
class Task:
    """One unit of swarm work."""

    task_id: str
    assigned_to: str  # robot id, or "" while unassigned
    priority: int  # lower runs first


def is_stale(last_seen_s: float | None, now_s: float, timeout_s: float) -> bool:
    """True when a peer has gone quiet for longer than timeout_s. Never having
    been seen counts as stale."""
    if last_seen_s is None:
        return True
    return (now_s - last_seen_s) > timeout_s


def alive_robots(
    last_seen: Mapping[str, float], now_s: float, timeout_s: float
) -> set[str]:
    return {
        robot
        for robot, seen in last_seen.items()
        if not is_stale(seen, now_s, timeout_s)
    }


def reassign(tasks: Iterable[Task], alive: set[str]) -> dict[str, str]:
    """Hand the orphaned tasks to the surviving robots (T-082).

    Returns {task_id: new_robot_id} for tasks whose owner is gone. Tasks that
    still have a live owner are untouched. When no robot is alive the result is
    empty and the caller keeps the work queued - inventing an owner would lose
    the task.

    Deterministic by construction: orphans are ordered by (priority, task_id)
    and each goes to the least loaded live robot, ties broken by robot id. The
    same inputs always produce the same plan, which is what lets SS11.2 replay
    a swarm run.
    """
    load = {robot: 0 for robot in alive}
    orphans = []
    for task in tasks:
        if task.assigned_to in alive:
            load[task.assigned_to] += 1
        else:
            orphans.append(task)

    if not alive:
        return {}

    plan: dict[str, str] = {}
    for task in sorted(orphans, key=lambda t: (t.priority, t.task_id)):
        target = min(load, key=lambda r: (load[r], r))
        plan[task.task_id] = target
        load[target] += 1
    return plan


def trip_deadline_s(
    timeout_s: float = LINK_TIMEOUT_S, trip_fraction: float = TRIP_FRACTION
) -> float:
    """When the robot-side guard must start its safe-state transition (T-083).

    The acceptance criterion is "safe within 2 s", so tripping AT 2 s fails it -
    the transition has to be finished by then. The fraction is the margin, and
    it is a parameter because the real transition time is a hardware number: a
    heavier robot with slower brakes needs a smaller fraction, and that is
    measured on the bench, not derived here.
    """
    if timeout_s <= 0.0:
        raise ValueError("timeout_s must be positive")
    if not 0.0 < trip_fraction <= 1.0:
        raise ValueError("trip_fraction must be in (0, 1]")
    return timeout_s * trip_fraction


def confirm_budget_s(
    timeout_s: float = LINK_TIMEOUT_S, trip_fraction: float = TRIP_FRACTION
) -> float:
    """How long the safety latch has to confirm the stop after the guard asked
    for it (T-083).

    The guard trips at trip_deadline_s and the robot must BE safe at timeout_s,
    so everything between the two belongs to the latch: publishing the trip,
    the watchdog node latching it, and the latched status coming back. Past
    this the criterion is breached and saying so in the log is the only honest
    move - the guard cannot cut power, only the L0 relay can (SS5.1).
    """
    return timeout_s - trip_deadline_s(timeout_s, trip_fraction)
