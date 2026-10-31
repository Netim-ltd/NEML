# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""T-082 ownership by lease, with injected time. No ROS, no sleeping."""

import pytest

from neml_swarm.assignment import LINK_TIMEOUT_S, trip_deadline_s
from neml_swarm.lease import (
    CLAIM_STAGGER_S,
    LEASE_TTL_S,
    Lease,
    claim,
    claim_rank,
    claimable,
    decode,
    encode,
    expired_tasks,
    is_expired,
    merge,
    reclaim_delay_s,
    renew,
)

FLEET = ("r01", "r02", "r03")


def held(task="t1", holder="r01", epoch=0, at=0.0, ttl=LEASE_TTL_S):
    return Lease(task, holder, epoch, at + ttl)


# ---------------------------------------------------------------- expiry


def test_lease_ttl_leaves_the_dropped_robot_time_to_stop_first():
    """T-082 must not hand work to a peer while the failed robot is still
    moving: the T-083 guard trips first, the lease expires after it."""
    assert trip_deadline_s() < LEASE_TTL_S == LINK_TIMEOUT_S


def test_expiry_is_inclusive():
    """At the expiry instant the lease is already dead. A lease that is alive
    'until strictly after' leaves a tick where two robots can both own it."""
    lease = held(at=0.0)
    assert not is_expired(lease, LEASE_TTL_S - 0.001)
    assert is_expired(lease, LEASE_TTL_S)


def test_renew_moves_the_expiry_and_nothing_else():
    lease = held(at=0.0, epoch=4)
    renewed = renew(lease, now_s=1.0)
    assert renewed.expires_at_s == 1.0 + LEASE_TTL_S
    assert (renewed.holder, renewed.epoch) == (lease.holder, lease.epoch)


def test_expired_tasks_is_sorted_so_every_robot_walks_them_alike():
    ledger = {
        "t3": held("t3", at=0.0),
        "t1": held("t1", at=0.0),
        "t2": held("t2", at=100.0),
    }
    assert expired_tasks(ledger, now_s=10.0) == ["t1", "t3"]


# ---------------------------------------------------------------- claiming


def test_an_unowned_task_is_free():
    lease = claim(None, "t1", "r02", now_s=5.0)
    assert lease == Lease("t1", "r02", 0, 5.0 + LEASE_TTL_S)


def test_a_live_lease_cannot_be_stolen():
    """The core T-082 guarantee: two robots that can hear each other never both
    own the same task."""
    current = held(holder="r01", at=0.0)
    assert claim(current, "t1", "r02", now_s=1.0) is None


def test_an_expired_lease_is_reclaimable_and_bumps_the_epoch():
    current = held(holder="r01", epoch=7, at=0.0)
    taken = claim(current, "t1", "r02", now_s=LEASE_TTL_S)
    assert taken is not None
    assert (taken.holder, taken.epoch) == ("r02", 8)


def test_the_holder_renewing_itself_keeps_its_epoch():
    current = held(holder="r01", epoch=3, at=0.0)
    again = claim(current, "t1", "r01", now_s=0.5)
    assert again is not None
    assert (again.holder, again.epoch) == ("r01", 3)


def test_a_revived_holder_loses_to_the_robot_that_took_over():
    """The failure this epoch exists for: r01 drops, r02 takes the task, r01
    comes back and renews. Without fencing both would now believe they own it."""
    original = held(holder="r01", epoch=0, at=0.0)
    taken = claim(original, "t1", "r02", now_s=LEASE_TTL_S)
    zombie = renew(original, now_s=LEASE_TTL_S + 10.0)  # later expiry, old epoch
    assert merge(taken, zombie).holder == "r02"


# ---------------------------------------------------------------- merge


def test_merge_takes_the_first_lease_it_hears():
    lease = held()
    assert merge(None, lease) is lease


def test_merge_is_order_independent():
    a = held(holder="r01", epoch=0, at=0.0)
    b = held(holder="r02", epoch=1, at=5.0)
    c = renew(a, now_s=3.0)
    assert merge(merge(merge(None, a), b), c) == merge(merge(merge(None, c), a), b)


def test_merge_prefers_the_newer_renewal_at_the_same_epoch():
    a = held(holder="r01", at=0.0)
    assert merge(a, renew(a, now_s=1.0)).expires_at_s == 1.0 + LEASE_TTL_S
    assert merge(renew(a, now_s=1.0), a).expires_at_s == 1.0 + LEASE_TTL_S


def test_merge_breaks_an_exact_tie_by_holder_so_the_order_is_total():
    a = Lease("t1", "r01", 1, 9.0)
    b = Lease("t1", "r02", 1, 9.0)
    assert merge(a, b) == merge(b, a) == b


def test_merge_refuses_to_mix_tasks():
    with pytest.raises(ValueError):
        merge(held("t1"), held("t2"))


# ---------------------------------------------------------------- staggering


def test_claim_rank_is_a_permutation_of_the_candidates():
    ranks = [claim_rank("t1", r, FLEET) for r in FLEET]
    assert sorted(ranks) == [0, 1, 2]


def test_claim_rank_is_stable_across_processes():
    """Pinned, not just 'deterministic': every robot computes this queue
    independently and they have to agree. hash() would not survive this."""
    assert [claim_rank("t7", r, FLEET) for r in FLEET] == [
        claim_rank("t7", r, reversed(FLEET)) for r in FLEET
    ]


def test_rank_depends_on_the_task_so_one_robot_does_not_inherit_everything():
    winners = {min(FLEET, key=lambda r: claim_rank(f"t{i}", r, FLEET)) for i in range(20)}
    assert len(winners) > 1


def test_rank_zero_waits_for_nothing():
    first = min(FLEET, key=lambda r: claim_rank("t1", r, FLEET))
    assert reclaim_delay_s("t1", first, FLEET) == 0.0


def test_a_non_candidate_cannot_be_ranked():
    with pytest.raises(ValueError):
        claim_rank("t1", "r09", FLEET)


# ---------------------------------------------------------------- claimable


def _dropped_ledger(at=0.0):
    return {"t1": held("t1", holder="r01", at=at)}


def test_nobody_grabs_a_live_lease():
    assert claimable(_dropped_ledger(), now_s=0.5, robot_id="r02", candidates=FLEET) is None


def test_the_dead_holder_is_out_of_the_running_for_its_own_task():
    ledger = _dropped_ledger()
    assert claimable(ledger, now_s=100.0, robot_id="r01", candidates=FLEET) is None


def test_the_first_ranked_survivor_takes_it_immediately_on_expiry():
    ledger = _dropped_ledger()
    survivors = {"r02", "r03"}
    first = min(survivors, key=lambda r: claim_rank("t1", r, survivors))
    assert claimable(ledger, LEASE_TTL_S, first, FLEET) == "t1"


def test_the_second_ranked_survivor_waits_out_its_stagger():
    ledger = _dropped_ledger()
    survivors = {"r02", "r03"}
    second = max(survivors, key=lambda r: claim_rank("t1", r, survivors))
    just_expired = LEASE_TTL_S
    assert claimable(ledger, just_expired, second, FLEET) is None
    assert claimable(ledger, just_expired + CLAIM_STAGGER_S, second, FLEET) == "t1"


def test_the_longest_orphaned_task_moves_first():
    ledger = {
        "t1": Lease("t1", "r01", 0, 10.0),
        "t2": Lease("t2", "r01", 0, 5.0),
    }
    assert claimable(ledger, now_s=100.0, robot_id="r02", candidates=FLEET) == "t2"


def test_a_robot_outside_the_roster_claims_nothing():
    assert claimable(_dropped_ledger(), 100.0, "r09", FLEET) is None


# ---------------------------------------------------------------- the wire


def test_round_trip():
    lease = Lease("t1", "r02", 3, 12.5)
    assert decode(encode(lease)) == lease


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "not json",
        "[]",
        '"t1"',
        "42",
        '{"task_id": "t1"}',
        '{"task_id": "t1", "holder": "r01", "epoch": "x", "expires_at_s": 1.0}',
        '{"task_id": "", "holder": "r01", "epoch": 0, "expires_at_s": 1.0}',
        '{"task_id": "t1", "holder": "", "epoch": 0, "expires_at_s": 1.0}',
        '{"task_id": "t1", "holder": "r01", "epoch": -1, "expires_at_s": 1.0}',
    ],
)
def test_junk_off_the_network_is_dropped_not_raised(payload):
    """SS5.4: the swarm link is untrusted input. A bad frame costs one message,
    never the node."""
    assert decode(payload) is None


def test_an_immortal_lease_cannot_be_smuggled_in():
    """NaN and Infinity are legal JSON numbers to Python. A NaN expiry compares
    false against every clock, so the task could never be reclaimed again."""
    assert decode('{"task_id": "t1", "holder": "r01", "epoch": 0, "expires_at_s": NaN}') is None
    assert (
        decode('{"task_id": "t1", "holder": "r01", "epoch": 0, "expires_at_s": Infinity}') is None
    )
