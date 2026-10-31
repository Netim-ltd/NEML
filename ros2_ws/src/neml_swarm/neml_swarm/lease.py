# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Task ownership by lease (NEML_SPEC.md T-082).

WHY A LEASE AND NOT AN ASSIGNMENT TABLE
    SS17.2 puts the swarm on WiFi with zenoh. A robot does not fail by telling
    anyone; it fails by going quiet, and the half of the fleet that can still
    hear each other has to keep working. A lease is the only ownership shape
    that survives that: holding a task means holding a lease that has to be
    renewed, so a robot that stopped talking stops owning, everywhere, at the
    same moment, with nobody needing to decide it.

    There is no central broker in this file. The coordinator (coordinator_node)
    watches leases and publishes an advisory plan, but it grants nothing: a
    peer takes an expired lease on its own (lease_agent_node). Kill the
    coordinator and handover still works.

THE RULES, ALL OF THEM
    1. A lease is (task_id, holder, epoch, expires_at_s). It expires by clock,
       not by message.
    2. Only an expired lease may be taken by someone else. A live one is
       refused, so two robots that can hear each other never both own a task.
    3. Taking bumps the epoch. A holder that comes back from the dead and
       renews at the old epoch loses to the new owner under `merge`, so a
       revived robot cannot silently keep driving a task it no longer has.
    4. `merge` is a total order over (epoch, expires_at_s, holder). Every node
       that has heard the same set of messages agrees on the owner, in any
       arrival order, with no round trip.

THE CEILING
    ponytail: this is leases, not consensus. Two robots that cannot hear each
    other CAN both claim the same expired lease - each sees only silence, and
    silence is indistinguishable from death. When the partition heals `merge`
    picks one winner deterministically and the loser sees its lease taken. That
    is correct for "move a box", wrong for "fire the actuator once". If a task
    ever becomes non-idempotent, this needs a quorum (raft over the roster) or
    a fencing token checked by the actuator - not a longer TTL.
"""

import hashlib
import json
import math
from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace

from neml_swarm.assignment import LINK_TIMEOUT_S

# How long a renewal buys. Deliberately equal to the T-083 link deadline: a
# robot that lost the link trips into the latched safe state at 80% of it
# (assignment.trip_deadline_s), so by the time a peer may take its work the
# robot has already stopped. Shorter would hand the task over to a robot that
# is still moving; longer would leave work stranded past the safe-state point.
LEASE_TTL_S = LINK_TIMEOUT_S

# Per-rank wait before a candidate claims an expired lease. Keeps three robots
# from grabbing the same orphan in the same millisecond on a lossy link; the
# loser hears the winner's claim during its own wait and stands down.
CLAIM_STAGGER_S = 0.25


@dataclass(frozen=True)
class Lease:
    """Ownership of one task for a bounded time."""

    task_id: str
    holder: str  # robot id
    epoch: int  # bumped on every change of holder
    expires_at_s: float


def is_expired(lease: Lease, now_s: float) -> bool:
    """A lease is dead the instant it reaches its expiry, not after it."""
    return now_s >= lease.expires_at_s


def renew(lease: Lease, now_s: float, ttl_s: float = LEASE_TTL_S) -> Lease:
    """Push the expiry out. Same holder, same epoch: a renewal is not a change
    of ownership and must not beat a peer's claim."""
    return replace(lease, expires_at_s=now_s + ttl_s)


def claim(
    current: Lease | None,
    task_id: str,
    claimant: str,
    now_s: float,
    ttl_s: float = LEASE_TTL_S,
) -> Lease | None:
    """Try to own `task_id`. None means refused - the current holder is alive.

    An unowned task is free. The holder renewing itself always succeeds. Anyone
    else has to wait for the expiry, and gets a bumped epoch when they take it.
    """
    if current is None:
        return Lease(task_id, claimant, 0, now_s + ttl_s)
    if current.holder == claimant:
        return renew(current, now_s, ttl_s)
    if not is_expired(current, now_s):
        return None
    return Lease(task_id, claimant, current.epoch + 1, now_s + ttl_s)


def merge(current: Lease | None, incoming: Lease) -> Lease:
    """Fold a lease heard from the network into what we already believe.

    Total order on (epoch, expires_at_s, holder), so the result does not depend
    on the order the messages arrived in - which on a lossy WiFi link is the
    only assumption worth making.
    """
    if current is None:
        return incoming
    if current.task_id != incoming.task_id:
        raise ValueError(f"cannot merge {incoming.task_id} into {current.task_id}")
    key = (incoming.epoch, incoming.expires_at_s, incoming.holder)
    return incoming if key > (current.epoch, current.expires_at_s, current.holder) else current


def expired_tasks(ledger: dict[str, Lease], now_s: float) -> list[str]:
    """Task ids whose owner stopped renewing. Sorted, so every robot walks them
    in the same order."""
    return sorted(t for t, lease in ledger.items() if is_expired(lease, now_s))


def claim_rank(task_id: str, robot_id: str, candidates: Iterable[str]) -> int:
    """Where `robot_id` stands in the queue for `task_id`.

    Ordered by a stable digest of (task_id, candidate) rather than by robot id,
    so r01 does not inherit every orphan in the fleet while r03 idles. Uses
    blake2b instead of hash(): PYTHONHASHSEED makes hash() differ per process,
    and every robot has to compute the same queue.
    """
    ranked = sorted(set(candidates), key=lambda r: _digest(task_id, r))
    if robot_id not in ranked:
        raise ValueError(f"{robot_id} is not a candidate for {task_id}")
    return ranked.index(robot_id)


def reclaim_delay_s(
    task_id: str,
    robot_id: str,
    candidates: Iterable[str],
    stagger_s: float = CLAIM_STAGGER_S,
) -> float:
    """How long after expiry this robot waits before claiming."""
    return claim_rank(task_id, robot_id, candidates) * stagger_s


def claimable(
    ledger: dict[str, Lease],
    now_s: float,
    robot_id: str,
    candidates: Iterable[str],
    stagger_s: float = CLAIM_STAGGER_S,
) -> str | None:
    """The one expired lease this robot may take right now, or None.

    One at a time, because a robot runs one task at a time. Among the leases
    whose stagger has elapsed it takes the one that has been orphaned longest,
    so work does not starve while newer orphans get picked up.

    The dead holder is removed from the candidate set before ranking, so the
    queue for a task is stable no matter which robot died. If the rank-0
    candidate is dead too, nobody claims during its slot and rank 1 takes it
    one stagger later - the delay self-heals without any liveness tracking.
    """
    best: str | None = None
    for task_id in expired_tasks(ledger, now_s):
        lease = ledger[task_id]
        if lease.holder == robot_id:
            continue
        others = set(candidates) - {lease.holder}
        if robot_id not in others:
            continue
        if now_s < lease.expires_at_s + reclaim_delay_s(task_id, robot_id, others, stagger_s):
            continue
        if best is None or lease.expires_at_s < ledger[best].expires_at_s:
            best = task_id
    return best


def _digest(task_id: str, robot_id: str) -> bytes:
    return hashlib.blake2b(f"{task_id}/{robot_id}".encode(), digest_size=8).digest()


def encode(lease: Lease) -> str:
    """Wire form. JSON on std_msgs/String, matching the rest of this package -
    the swarm task schema is still moving (T-084) and does not belong in a
    compiled neml_msgs interface yet."""
    return json.dumps(asdict(lease), sort_keys=True)


def decode(payload: str) -> Lease | None:
    """Parse a lease heard from the swarm network, or None if it is junk.

    The network is untrusted input (SS5.4). A malformed or hostile frame must
    cost one dropped message, never the node that received it, so every failure
    mode collapses to None and the caller ignores it.
    """
    try:
        raw = json.loads(payload)
        lease = Lease(
            task_id=str(raw["task_id"]),
            holder=str(raw["holder"]),
            epoch=int(raw["epoch"]),
            expires_at_s=float(raw["expires_at_s"]),
        )
    except (TypeError, ValueError, KeyError):
        return None
    # NaN compares false against everything, so a NaN expiry would be a lease
    # that never expires and a task nobody can ever take back.
    if not math.isfinite(lease.expires_at_s) or lease.epoch < 0:
        return None
    if not lease.task_id or not lease.holder:
        return None
    return lease
