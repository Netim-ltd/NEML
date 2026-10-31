# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""T-074 budget accounting, with injected timestamps.

The end-to-end number itself is measured against a live graph in
test_propagation_launch.py and against hardware in T-075. What is checked here
is the accounting: that the budget is 50 ms, that it is measured from ingress,
and that a chain which blows it is reported as blown rather than averaged away.
"""

import ast
import pathlib

import pytest

from neml_safety.propagation import ESTOP_BUDGET_MS, Trace, now_ns

MS = 1_000_000


def test_the_budget_is_the_acceptance_criterion():
    """T-074 says 50 ms. Nobody gets to quietly raise it."""
    assert ESTOP_BUDGET_MS == 50.0


def test_the_clock_is_monotonic_and_not_the_ros_clock():
    """A latency figure that a fast simulation can produce is worthless."""
    assert now_ns() <= now_ns()


def test_nothing_stamped_yet_is_zero_not_a_pass():
    trace = Trace(ingress_ns=0)
    assert trace.total_ms == 0.0


def test_every_hop_is_measured_from_ingress():
    trace = Trace(ingress_ns=100 * MS)
    trace.record("controller", 105 * MS)
    trace.record("swarm", 112 * MS)
    assert trace.elapsed_ms("controller") == pytest.approx(5.0)
    assert trace.elapsed_ms("swarm") == pytest.approx(12.0)
    assert trace.total_ms == pytest.approx(12.0)


def test_the_spec_chain_fits_the_budget():
    """The SS5.1 chain the node documents: aux MCU sample, transport, evaluate,
    publish, then two subscribers. ~17 ms of node-side budget plus the hops."""
    trace = Trace(ingress_ns=0)
    trace.record("transport", 1 * MS)
    trace.record("evaluate", 6 * MS)
    trace.record("published", 7 * MS)
    trace.record("motion_controller", 9 * MS)
    trace.record("swarm_coordinator", 12 * MS)
    assert not trace.over_budget()
    assert trace.total_ms == pytest.approx(12.0)


def test_one_slow_subscriber_blows_the_whole_budget():
    """The failure this exists to catch: every hop looks fine on its own and
    the robot still learns about the e-stop too late."""
    trace = Trace(ingress_ns=0)
    trace.record("published", 7 * MS)
    trace.record("a_subscriber_that_blocked", 60 * MS)
    assert trace.over_budget()


def test_the_budget_edge_is_not_a_failure():
    trace = Trace(ingress_ns=0)
    trace.record("published", 50 * MS)
    assert not trace.over_budget()
    trace.record("one_microsecond_later", 50 * MS + 1000)
    assert trace.over_budget()


def test_the_breakdown_names_the_hop_that_ate_the_budget():
    trace = Trace(ingress_ns=0)
    trace.record("transport", 1 * MS)
    trace.record("published", 2 * MS)
    trace.record("slow_subscriber", 70 * MS)
    worst = max(trace.breakdown(), key=lambda hop: hop[1])
    assert worst[0] == "slow_subscriber"
    assert worst[1] == pytest.approx(68.0)


def test_the_report_says_over_budget_out_loud():
    trace = Trace(ingress_ns=0, label="estop")
    trace.record("published", 80 * MS)
    report = trace.report()
    assert "OVER BUDGET" in report
    assert "80.000 ms" in report
    assert "published" in report


def test_a_healthy_report_is_quiet():
    trace = Trace(ingress_ns=0)
    trace.record("published", 3 * MS)
    assert "ok" in trace.report()
    assert "OVER BUDGET" not in trace.report()


def test_time_going_backwards_is_an_error_not_a_negative_latency():
    """Two clocks mixed by accident would otherwise report a stop that arrived
    before it was sent, and the budget would pass."""
    trace = Trace(ingress_ns=10 * MS)
    with pytest.raises(ValueError):
        trace.record("impossible", 9 * MS)


def test_an_unrecorded_hop_is_an_error_not_zero():
    trace = Trace(ingress_ns=0)
    trace.record("published", MS)
    with pytest.raises(KeyError):
        trace.elapsed_ms("never_arrived")


def test_recording_without_a_timestamp_uses_the_monotonic_clock():
    """This is the subscriber path: a subscriber stamps itself on arrival."""
    trace = Trace(ingress_ns=now_ns())
    hop = trace.record("subscriber")
    assert hop.at_ns >= trace.ingress_ns
    assert trace.total_ms < ESTOP_BUDGET_MS


# ------------------------------------------------------ SS17.2 QoS enforcement


def _endpoint_qos(package_dir):
    """Every create_publisher / create_subscription in the package, with the
    name of the QoS argument it was given.

    Parsed rather than grepped because the calls span lines. Reading the source
    is the point: rclpy accepts a bare int for `qos_profile` and silently gives
    you RELIABLE / VOLATILE / KEEP_LAST(n), which is the wrong profile for two
    of the four SS17.2 topic classes and looks completely normal in review.
    """
    found = []
    for source in sorted(package_dir.glob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in ("create_publisher", "create_subscription"):
                continue
            qos = node.args[-1] if node.args else None
            found.append(
                (
                    source.name,
                    node.lineno,
                    qos.id if isinstance(qos, ast.Name) else ast.dump(qos),
                )
            )
    return found


def test_every_endpoint_uses_a_profile_from_the_qos_table():
    """SS17.2 gives four topic classes four profiles. A node that skips the
    table gets the rclpy default, and a `state` topic published VOLATILE is a
    late joiner that is never told the robot is latched."""
    package = pathlib.Path(__file__).resolve().parent.parent / "neml_safety"
    endpoints = _endpoint_qos(package)
    assert endpoints, "no publishers or subscribers found - did the package move?"
    for name, lineno, qos in endpoints:
        assert qos in {"STATE_QOS", "CMD_QOS", "TELEMETRY_QOS"}, (
            f"{name}:{lineno} uses {qos} instead of an SS17.2 profile"
        )
