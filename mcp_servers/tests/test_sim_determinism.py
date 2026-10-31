# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 11.2 determinism (T-036).

Gazebo is not installed on the authoring host, so the maths that decides whether
a run may influence evolution is tested here instead: the 2% comparison, the
flagging, the rule-3 exclusion and the ten-run harness bookkeeping. The 2%
measurement itself still has to be executed once on the lab host.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

from mcp_servers.neml_mcp_sim import determinism, server
from mcp_servers.tests.test_sim import FakeGpuLock, FakeRunner, call

# --- the comparison (SPEC 11.2 rule 3) --------------------------------------


def test_identical_metrics_have_no_deviation() -> None:
    assert determinism.deviations({"d": 2.0}, {"d": 2.0}) == {"d": 0.0}


def test_deviation_is_relative_to_the_baseline() -> None:
    assert determinism.deviations({"d": 10.0}, {"d": 10.5})["d"] == pytest.approx(0.05)


def test_a_metric_on_one_side_only_is_not_comparable() -> None:
    devs = determinism.deviations({"d": 1.0}, {"d": 1.0, "energy_wh": 3.0})
    assert devs["energy_wh"] == math.inf
    assert determinism.within_tolerance({"d": 1.0}, {"d": 1.0, "energy_wh": 3.0}) is False


def test_zero_baseline_does_not_divide_by_zero() -> None:
    assert determinism.deviations({"d": 0.0}, {"d": 0.0})["d"] == 0.0
    assert determinism.within_tolerance({"d": 0.0}, {"d": 0.5}) is False


def test_the_boundary_is_inclusive_at_two_percent() -> None:
    assert determinism.within_tolerance({"d": 100.0}, {"d": 102.0}) is True
    assert determinism.within_tolerance({"d": 100.0}, {"d": 102.001}) is False


def test_a_run_that_measured_nothing_is_not_deterministic() -> None:
    """Empty metrics are not agreement, they are an absence of evidence."""
    assert determinism.within_tolerance({}, {}) is False


# --- the ten-run verdict ----------------------------------------------------


def test_ten_matching_runs_pass() -> None:
    runs = [{"distance_m": 2.0, "energy_wh": 1.0} for _ in range(determinism.DEFAULT_RUNS)]
    report = determinism.compare_runs(7, "abc", runs)
    assert report.runs == 10
    assert report.deterministic is True
    assert report.max_deviation == 0.0


def test_one_bad_run_out_of_ten_fails_the_set() -> None:
    runs: list[dict[str, float]] = [{"distance_m": 2.0} for _ in range(10)]
    runs[6] = {"distance_m": 2.1}  # 5%
    report = determinism.compare_runs(7, "abc", runs)
    assert report.deterministic is False
    assert report.worst_metric == "distance_m"
    assert report.max_deviation == pytest.approx(0.05)


def test_every_repeat_is_compared_to_the_first_run_not_its_neighbour() -> None:
    """A 0.5% creep per run is 4.5% by run ten; neighbour comparison misses it."""
    runs = [{"distance_m": 2.0 * (1.0 + 0.005 * i)} for i in range(10)]
    assert determinism.compare_runs(7, "abc", runs).deterministic is False


def test_a_verdict_needs_at_least_two_runs() -> None:
    with pytest.raises(ValueError, match="at least two runs"):
        determinism.compare_runs(7, "abc", [{"distance_m": 1.0}])


# --- the exclusion (SPEC 11.2 rule 3) ---------------------------------------


def test_flagged_runs_are_dropped_before_an_evolution_decision() -> None:
    rows = [
        {"id": 1, "deterministic": True},
        {"id": 2, "deterministic": False},
        {"id": 3, "deterministic": True},
    ]
    assert [r["id"] for r in determinism.usable_runs(rows)] == [1, 3]


def test_a_run_with_no_verdict_is_dropped_too() -> None:
    assert determinism.usable_runs([{"id": 1}]) == []
    assert determinism.usable_runs([{"id": 1, "deterministic": "yes"}]) == []


def test_the_server_exposes_the_exclusion() -> None:
    """The sim owns the verdict, so it owns the filter - as an import, not as an
    MCP tool: SPEC 6.3 names twelve tools and this is not one of them."""
    assert server.evolution_input([{"deterministic": True}]) == [{"deterministic": True}]
    assert "evolution_input" not in server.TOOLS


# --- the harness (T-036) ----------------------------------------------------


@pytest.fixture
def lab(tmp_path: Path) -> tuple[FakeRunner, Path]:
    worlds = tmp_path / "worlds"
    worlds.mkdir()
    (worlds / "flat.sdf").write_text("<sdf/>", encoding="utf-8")
    urdf = tmp_path / "robot.urdf"
    urdf.write_text("<robot name='r'/>", encoding="utf-8")
    runner = FakeRunner()
    server.configure(reset_state=True, runner=runner, gpu_lock=FakeGpuLock(), world_dir=worlds)
    return runner, urdf


def test_the_harness_runs_ten_worlds_and_passes_on_agreement(lab: tuple[FakeRunner, Path]) -> None:
    runner, urdf = lab
    runner.metrics = [{"distance_m": 2.0} for _ in range(10)]
    report = call(server.determinism_check("flat", 42, str(urdf), "fast", 10, 1.0))
    assert report.runs == 10 and report.deterministic is True
    assert report.seed == 42 and len(report.sim_version) == 12
    # A fresh world per repeat: leaked state is what this harness hunts.
    assert runner.ops.count("load_world") == 10
    assert runner.ops.count("teardown") == 10


def test_the_harness_flags_a_drifting_set(lab: tuple[FakeRunner, Path]) -> None:
    runner, urdf = lab
    runner.metrics = [{"distance_m": 2.0}] * 9 + [{"distance_m": 2.2}]
    report = call(server.determinism_check("flat", 42, str(urdf), "fast", 10, 1.0))
    assert report.deterministic is False
    assert report.max_deviation == pytest.approx(0.10)


def test_the_harness_records_the_randomisation_it_ran_under(
    lab: tuple[FakeRunner, Path],
) -> None:
    runner, urdf = lab
    runner.metrics = [{"distance_m": 2.0} for _ in range(3)]
    report = call(server.determinism_check("flat", 42, str(urdf), "fast", 3, 1.0))
    assert report.randomization["seed"] == 42
    assert report.randomization["span"] == 0.15


def test_the_harness_bounds_the_call_not_the_sim_clock(lab: tuple[FakeRunner, Path]) -> None:
    """The sim-time bound belongs in the condition. Handing `run_until` the sim
    duration as its call timeout makes a ten-second run at real_time_factor 0
    fail whenever the host is slower than 1x - a determinism harness that fails
    on machine speed measures the machine, not the simulator."""
    runner, urdf = lab
    runner.metrics = [{"distance_m": 2.0} for _ in range(2)]
    call(server.determinism_check("flat", 42, str(urdf), "fast", 2, 10.0, timeout_s=90.0))
    payload = runner.payloads[runner.ops.index("run_until")]["req"]
    assert payload["condition"] == "sim_time_s>=10.0"
    assert payload["timeout_s"] == 90.0


def test_the_harness_refuses_a_single_run(lab: tuple[FakeRunner, Path]) -> None:
    _runner, urdf = lab
    with pytest.raises(server.SimStateError):
        call(server.determinism_check("flat", 42, str(urdf), "fast", 1, 1.0))


def test_the_harness_tears_the_world_down_when_a_run_explodes(
    lab: tuple[FakeRunner, Path],
) -> None:
    runner, urdf = lab
    runner.fail_on = "run_until"
    with pytest.raises(server.SimError):
        call(server.determinism_check("flat", 42, str(urdf), "fast", 10, 1.0))
    assert runner.ops.count("teardown") == 1


# --- SPEC 11.2 rule 4: no wall clock anywhere -------------------------------

_SIM_DIRS = (
    server.REPO_ROOT / "mcp_servers" / "neml_mcp_sim",
    server.REPO_ROOT / "ros2_ws" / "src" / "neml_sim" / "neml_sim",
    server.REPO_ROOT / "ros2_ws" / "src" / "neml_sim" / "launch",
)
SIM_SOURCES = sorted(path for directory in _SIM_DIRS for path in directory.glob("*.py"))

# `asyncio.wait_for` bounds an external process and is not decision logic, so the
# ban is on reading a clock value, not on having a timeout.
WALL_CLOCK = re.compile(
    r"\b(?:time\.(?:time|monotonic|perf_counter|process_time)|"
    r"datetime\.(?:now|utcnow|today)|date\.today)\s*\(|"
    r"^\s*(?:import\s+(?:time|datetime)\b|from\s+(?:time|datetime)\s+import)",
    re.MULTILINE,
)


@pytest.mark.parametrize("source", SIM_SOURCES, ids=lambda p: str(p.relative_to(server.REPO_ROOT)))
def test_no_wall_clock_in_the_simulation_layer(source: Path) -> None:
    """SPEC 11.2 rule 4 is absolute: sim time is the only time that exists.

    A wall-clock read here would not raise, it would quietly make runs
    irreproducible, so the guard is a grep rather than a behaviour test.
    """
    hits = WALL_CLOCK.findall(source.read_text(encoding="utf-8"))
    assert not hits, f"{source.name} reads the wall clock: {hits}"


def test_the_guard_catches_a_wall_clock_read() -> None:
    """The grep above only protects anything if it actually matches."""
    for bad in ("import time\n", "from datetime import datetime\n", "x = time.time()\n"):
        assert WALL_CLOCK.search(bad), bad
    assert not WALL_CLOCK.search("await asyncio.wait_for(p, timeout=timeout_s)\n")
    assert not WALL_CLOCK.search("sim_time_s = out['sim_time_s']\n")
