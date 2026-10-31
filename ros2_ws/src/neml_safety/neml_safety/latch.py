# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Pure safety-latch state machine. No rclpy, no clock, no I/O: every time
value is passed in, so the whole of T-074 can be tested without a ROS graph
and without waiting for real seconds.

NEML_SPEC.md SS5.1 is the contract this implements in software:
  - the watchdog MCU expects a heartbeat every 50 ms and opens the motor relay
    after 150 ms of silence,
  - the e-stop is a normally-closed loop,
  - neither of those is this code. This is the software mirror that lets the
    rest of the stack learn about the event and stop commanding motion.
"""

from dataclasses import dataclass

INF = float("inf")

# Mirrors of neml_msgs/SafetyStatus REASON_*. Duplicated on purpose so this
# module imports on a machine with no ROS; watchdog_node.py asserts at import
# time that the two sets still agree, so they cannot drift silently.
REASON_NONE = 0
REASON_ESTOP = 1
REASON_WATCHDOG_TIMEOUT = 2
REASON_OVERCURRENT = 3
REASON_OVERTEMP = 4
REASON_LINK_LOSS = 5
REASON_OPERATOR = 6


@dataclass(frozen=True)
class Verdict:
    """What the rest of the stack is told after one evaluation."""

    latched: bool
    reason: int
    heartbeat_age_s: float
    watchdog_ok: bool
    estop_engaged: bool
    motors_enabled: bool
    reset_required: bool


class SafetyLatch:
    """Latching stop. Once it closes it stays closed until an operator calls
    :meth:`reset` AND every cause has cleared. It never clears itself."""

    def __init__(self, heartbeat_timeout_s: float = 0.150, start_latched: bool = True) -> None:
        if heartbeat_timeout_s <= 0.0:
            raise ValueError("heartbeat_timeout_s must be positive")
        self.heartbeat_timeout_s = heartbeat_timeout_s
        self._last_heartbeat: float | None = None
        self._estop_engaged = False
        self._latched = start_latched
        # A latch we were born with has no single cause; say so honestly.
        self._reason = REASON_OPERATOR if start_latched else REASON_NONE
        self._latched_at: float | None = 0.0 if start_latched else None

    # ---------------------------------------------------------------- inputs
    def heartbeat(self, now: float) -> None:
        """Called on every heartbeat sample from the motion controller."""
        self._last_heartbeat = now

    def set_estop(self, engaged: bool, now: float) -> None:
        """Called on every e-stop line sample. Engaging latches immediately;
        releasing does NOT unlatch - that needs an operator reset."""
        self._estop_engaged = engaged
        if engaged:
            self._close(REASON_ESTOP, now)

    def trip(self, reason: int, now: float) -> None:
        """Latch from an external cause: overcurrent, overtemp, link loss
        (T-083) or an operator stop."""
        self._close(reason, now)

    # ----------------------------------------------------------------- query
    def heartbeat_age(self, now: float) -> float:
        if self._last_heartbeat is None:
            return INF
        return max(0.0, now - self._last_heartbeat)

    def causes_active(self, now: float) -> bool:
        """True while something would immediately re-latch."""
        return self._estop_engaged or self.heartbeat_age(now) > self.heartbeat_timeout_s

    def evaluate(self, now: float) -> Verdict:
        """One step of the state machine. Cheap enough to run at 200 Hz."""
        age = self.heartbeat_age(now)
        watchdog_ok = age <= self.heartbeat_timeout_s
        if not watchdog_ok:
            self._close(REASON_WATCHDOG_TIMEOUT, now)
        if self._estop_engaged:
            self._close(REASON_ESTOP, now)
        return Verdict(
            latched=self._latched,
            reason=self._reason,
            heartbeat_age_s=age,
            watchdog_ok=watchdog_ok,
            estop_engaged=self._estop_engaged,
            motors_enabled=not self._latched,
            reset_required=self._latched,
        )

    @property
    def latched_at(self) -> float | None:
        return self._latched_at

    # ----------------------------------------------------------------- reset
    def reset(self, now: float) -> tuple[bool, str]:
        """Explicit operator reset. Refused while any cause is still present,
        so a stuck e-stop or a dead motion controller cannot be cleared by
        spamming the service."""
        if not self._latched:
            return True, "not latched"
        if self._estop_engaged:
            return False, "e-stop still engaged"
        age = self.heartbeat_age(now)
        if age > self.heartbeat_timeout_s:
            return False, f"no heartbeat for {age:.3f} s"
        self._latched = False
        self._reason = REASON_NONE
        self._latched_at = None
        return True, "reset"

    # ---------------------------------------------------------------- private
    def _close(self, reason: int, now: float) -> None:
        if self._latched:
            # First cause wins: the operator needs to know what started it,
            # not what happened afterwards as a consequence.
            return
        self._latched = True
        self._reason = reason
        self._latched_at = now
