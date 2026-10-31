# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""T-074 logic, tested with injected time so it runs in milliseconds."""

import pytest

from neml_safety.latch import (
    REASON_ESTOP,
    REASON_LINK_LOSS,
    REASON_NONE,
    REASON_OPERATOR,
    REASON_WATCHDOG_TIMEOUT,
    SafetyLatch,
)

TIMEOUT = 0.150  # SS5.1 watchdog timeout


def _running(t0=0.0):
    """A latch that has been reset into the running state at t0."""
    latch = SafetyLatch(heartbeat_timeout_s=TIMEOUT)
    latch.heartbeat(t0)
    assert latch.reset(t0) == (True, "reset")
    return latch


def test_boots_latched_and_demands_an_operator():
    latch = SafetyLatch(heartbeat_timeout_s=TIMEOUT)
    verdict = latch.evaluate(0.0)
    assert verdict.latched
    assert verdict.reset_required
    assert not verdict.motors_enabled
    assert verdict.reason == REASON_OPERATOR


def test_may_boot_unlatched_for_bench_work():
    latch = SafetyLatch(heartbeat_timeout_s=TIMEOUT, start_latched=False)
    latch.heartbeat(0.0)
    assert latch.evaluate(0.0).motors_enabled


def test_running_state_is_clean():
    latch = _running()
    verdict = latch.evaluate(0.10)
    assert not verdict.latched
    assert verdict.watchdog_ok
    assert verdict.motors_enabled
    assert verdict.reason == REASON_NONE
    assert verdict.heartbeat_age_s == pytest.approx(0.10)


def test_heartbeat_loss_latches_after_the_timeout_and_not_before():
    latch = _running()
    assert not latch.evaluate(TIMEOUT).latched
    verdict = latch.evaluate(TIMEOUT + 0.001)
    assert verdict.latched
    assert verdict.reason == REASON_WATCHDOG_TIMEOUT
    assert not verdict.watchdog_ok


def test_heartbeat_returning_does_not_unlatch():
    """The hardware relay has already opened. Software must not pretend the
    session can continue just because the link came back."""
    latch = _running()
    latch.evaluate(0.5)
    latch.heartbeat(0.6)
    assert latch.evaluate(0.6).latched


def test_estop_latches_on_the_same_sample():
    latch = _running()
    latch.set_estop(True, 0.05)
    verdict = latch.evaluate(0.05)
    assert verdict.latched
    assert verdict.estop_engaged
    assert verdict.reason == REASON_ESTOP
    assert latch.latched_at == pytest.approx(0.05)


def test_reset_refused_while_estop_is_still_engaged():
    latch = _running()
    latch.set_estop(True, 0.05)
    ok, message = latch.reset(0.06)
    assert not ok
    assert "e-stop" in message
    assert latch.evaluate(0.06).latched


def test_reset_refused_while_heartbeat_is_stale():
    latch = _running()
    latch.evaluate(1.0)
    ok, message = latch.reset(1.0)
    assert not ok
    assert "heartbeat" in message


def test_reset_succeeds_once_every_cause_cleared():
    latch = _running()
    latch.set_estop(True, 0.05)
    latch.set_estop(False, 0.20)
    latch.heartbeat(0.20)
    assert latch.reset(0.20) == (True, "reset")
    assert latch.evaluate(0.20).motors_enabled


def test_first_cause_wins():
    latch = _running()
    latch.set_estop(True, 0.05)
    latch.trip(REASON_LINK_LOSS, 0.06)
    assert latch.evaluate(0.06).reason == REASON_ESTOP


def test_link_loss_trip_is_a_first_class_cause():
    """T-083: the link guard trips this latch, it does not invent its own."""
    latch = _running()
    latch.trip(REASON_LINK_LOSS, 2.0)
    assert latch.evaluate(2.0).reason == REASON_LINK_LOSS


def test_never_seen_heartbeat_reports_infinite_age():
    latch = SafetyLatch(heartbeat_timeout_s=TIMEOUT, start_latched=False)
    assert latch.evaluate(0.0).heartbeat_age_s == float("inf")


def test_rejects_nonsense_timeout():
    with pytest.raises(ValueError):
        SafetyLatch(heartbeat_timeout_s=0.0)
