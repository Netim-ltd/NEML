# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""T-082 handover and T-083 liveness, with injected time."""

import ast
import pathlib

import pytest

from neml_swarm.assignment import (
    LINK_TIMEOUT_S,
    TRIP_FRACTION,
    Task,
    alive_robots,
    confirm_budget_s,
    is_stale,
    reassign,
    trip_deadline_s,
)


def test_link_timeout_matches_the_acceptance_criterion():
    """T-083 says 2 seconds. Nobody gets to quietly raise it."""
    assert LINK_TIMEOUT_S == 2.0


def test_never_seen_peer_is_stale():
    assert is_stale(None, now_s=0.0, timeout_s=LINK_TIMEOUT_S)


def test_stale_boundary():
    assert not is_stale(0.0, now_s=2.0, timeout_s=2.0)
    assert is_stale(0.0, now_s=2.001, timeout_s=2.0)


def test_alive_set_drops_the_quiet_robot():
    last_seen = {"r01": 9.9, "r02": 7.0, "r03": 10.0}
    assert alive_robots(last_seen, now_s=10.0, timeout_s=2.0) == {"r01", "r03"}


def test_dropped_robot_work_moves_to_the_survivors():
    tasks = [
        Task("t1", "r01", 0),
        Task("t2", "r02", 0),
        Task("t3", "r02", 1),
    ]
    plan = reassign(tasks, alive={"r01", "r03"})
    assert set(plan) == {"t2", "t3"}
    # r01 already carries t1, so the first orphan goes to the idle r03.
    assert plan["t2"] == "r03"
    assert plan["t3"] == "r01"


def test_live_owners_are_left_alone():
    tasks = [Task("t1", "r01", 0), Task("t2", "r02", 0)]
    assert reassign(tasks, alive={"r01", "r02"}) == {}


def test_unassigned_tasks_get_an_owner():
    plan = reassign([Task("t1", "", 0)], alive={"r02"})
    assert plan == {"t1": "r02"}


def test_nothing_is_invented_when_the_swarm_is_empty():
    """Losing every robot must not lose the task."""
    assert reassign([Task("t1", "r01", 0)], alive=set()) == {}


def test_plan_is_deterministic_regardless_of_input_order():
    tasks = [Task("t3", "gone", 1), Task("t1", "gone", 0), Task("t2", "gone", 0)]
    first = reassign(tasks, alive={"r01", "r02"})
    second = reassign(list(reversed(tasks)), alive={"r01", "r02"})
    assert first == second


def test_load_is_balanced_not_dumped_on_one_robot():
    tasks = [Task(f"t{i}", "gone", 0) for i in range(6)]
    plan = reassign(tasks, alive={"r01", "r02", "r03"})
    counts = {robot: list(plan.values()).count(robot) for robot in {"r01", "r02", "r03"}}
    assert set(counts.values()) == {2}


# --------------------------------------------------------- T-083 safe-state timer


def test_the_guard_trips_before_the_deadline_not_at_it():
    """"Safe within 2 s" means the transition is finished by 2 s. Starting it
    at 2 s fails the criterion."""
    assert trip_deadline_s() == pytest.approx(1.6)
    assert trip_deadline_s() < LINK_TIMEOUT_S


def test_the_margin_is_tunable_because_it_is_a_hardware_number():
    """A heavier robot brakes slower. The knob is here, the value is measured
    on the bench."""
    assert trip_deadline_s(2.0, 0.5) == pytest.approx(1.0)
    assert TRIP_FRACTION == 0.8


def test_a_full_fraction_is_allowed_and_leaves_no_margin():
    assert trip_deadline_s(2.0, 1.0) == 2.0


@pytest.mark.parametrize("fraction", [0.0, -0.1, 1.5])
def test_a_nonsense_margin_is_refused(fraction):
    with pytest.raises(ValueError):
        trip_deadline_s(2.0, fraction)


def test_a_nonsense_timeout_is_refused():
    with pytest.raises(ValueError):
        trip_deadline_s(0.0, 0.8)


def test_the_latch_gets_the_rest_of_the_two_seconds_to_confirm():
    """Tripping is not stopping. Everything between the trip and the deadline
    belongs to the safety latch answering back."""
    assert confirm_budget_s() == pytest.approx(0.4)
    assert trip_deadline_s() + confirm_budget_s() == pytest.approx(LINK_TIMEOUT_S)


def test_the_confirm_budget_follows_the_margin_knob():
    """Brake harder, trip later, less time left to confirm. The two numbers
    cannot drift apart because one is defined from the other."""
    assert confirm_budget_s(2.0, 0.5) == pytest.approx(1.0)
    assert confirm_budget_s(2.0, 1.0) == pytest.approx(0.0)


def test_no_confirm_budget_is_refused_at_the_source():
    with pytest.raises(ValueError):
        confirm_budget_s(2.0, 0.0)



# ------------------------------------------------- SS17.2 camera egress rule


def test_the_swarm_package_puts_no_camera_stream_on_the_swarm_network():
    """SS17.2: "Kamera akisi ham olarak swarm agina verilmez." The one place
    frames are allowed to leave a robot is neml_perception's gate, compressed
    and only while somebody is subscribed. This package must never grow a
    second path, so the whole source tree is checked, not one file."""
    package = pathlib.Path(__file__).resolve().parent.parent / "neml_swarm"
    for source in package.glob("*.py"):
        text = source.read_text(encoding="utf-8").lower()
        assert "sensor_msgs" not in text, f"{source.name} reaches for image messages"
        assert "camera" not in text, f"{source.name} names a camera topic"


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
    package = pathlib.Path(__file__).resolve().parent.parent / "neml_swarm"
    endpoints = _endpoint_qos(package)
    assert endpoints, "no publishers or subscribers found - did the package move?"
    for name, lineno, qos in endpoints:
        assert qos in {"STATE_QOS", "CMD_QOS", "TELEMETRY_QOS"}, (
            f"{name}:{lineno} uses {qos} instead of an SS17.2 profile"
        )
