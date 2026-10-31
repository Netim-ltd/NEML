# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 11.4 domain randomisation in the sim server (T-037).

The six parameters are sampled from the run seed by
neml_brain.evolution.randomization and applied by this server. What is tested
here is the part the sim owns: that the sample happens once per run, before any
physics, from the CAD masses in the URDF that was actually spawned, and that the
values come back out with the run record so the run can be replayed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_servers.neml_mcp_sim import server
from mcp_servers.tests.test_sim import FakeGpuLock, FakeRunner, call

SPAN = 0.15  # SPEC 11.4
URDF = """<?xml version="1.0"?>
<robot name="quad">
  <link name="base_link"><inertial><mass value="1.900"/></inertial></link>
  <link name="fl_upper"><inertial><mass value="0.180"/></inertial></link>
  <link name="imu_link"/>
</robot>
"""

# The six SPEC 11.4 rows. link_masses_kg comes from the URDF, motor_torque_constant
# is a datasheet multiplier, the rest have fixed nominals.
SIX = (
    "surface_friction",
    "link_masses_kg",
    "imu_noise_sigma_rads",
    "encoder_noise_sigma_rad",
    "control_latency_s",
    "motor_torque_constant",
)
NOMINALS = {
    "surface_friction": 0.7,
    "imu_noise_sigma_rads": 0.01,
    "encoder_noise_sigma_rad": 0.002,
    "control_latency_s": 0.008,
    "motor_torque_constant": server.NOMINAL_TORQUE_SCALE,
}


@pytest.fixture
def lab(tmp_path: Path) -> Path:
    worlds = tmp_path / "worlds"
    worlds.mkdir()
    (worlds / "flat.sdf").write_text("<sdf/>", encoding="utf-8")
    urdf = tmp_path / "quad.urdf"
    urdf.write_text(URDF, encoding="utf-8")
    server.configure(
        reset_state=True, runner=FakeRunner(), gpu_lock=FakeGpuLock(), world_dir=worlds
    )
    return urdf


def run(urdf: Path, seed: int = 42, ns: str = "r1") -> server.RobotHandle:
    call(server.load_world("flat", seed, "fast"))
    return call(server.spawn_robot(str(urdf), server.Pose(), ns))


def test_all_six_parameters_are_recorded_on_the_run(lab: Path) -> None:
    record = run(lab).randomization
    assert set(SIX) <= set(record)
    assert record["seed"] == 42 and record["span"] == SPAN


def test_every_value_stays_inside_plus_minus_fifteen_percent(lab: Path) -> None:
    record = run(lab).randomization
    for name, nominal in NOMINALS.items():
        assert nominal * (1 - SPAN) <= record[name] <= nominal * (1 + SPAN), name
    for name, nominal in {"base_link": 1.900, "fl_upper": 0.180}.items():
        assert nominal * (1 - SPAN) <= record["link_masses_kg"][name] <= nominal * (1 + SPAN), name


def test_masses_come_from_the_urdf_that_was_spawned(lab: Path) -> None:
    """CAD value, SPEC 11.4 - and only links that declare one."""
    assert set(run(lab).randomization["link_masses_kg"]) == {"base_link", "fl_upper"}


def test_a_urdf_without_inertials_still_randomises_the_other_five(tmp_path: Path) -> None:
    worlds = tmp_path / "worlds"
    worlds.mkdir()
    (worlds / "flat.sdf").write_text("<sdf/>", encoding="utf-8")
    urdf = tmp_path / "bare.urdf"
    urdf.write_text("<robot name='r'/>", encoding="utf-8")
    server.configure(
        reset_state=True, runner=FakeRunner(), gpu_lock=FakeGpuLock(), world_dir=worlds
    )
    record = run(urdf).randomization
    assert record["link_masses_kg"] == {}
    assert record["surface_friction"] != 0.7


def test_a_urdf_that_is_not_xml_is_a_typed_error(tmp_path: Path) -> None:
    worlds = tmp_path / "worlds"
    worlds.mkdir()
    (worlds / "flat.sdf").write_text("<sdf/>", encoding="utf-8")
    broken = tmp_path / "broken.urdf"
    broken.write_text("not xml at all", encoding="utf-8")
    server.configure(
        reset_state=True, runner=FakeRunner(), gpu_lock=FakeGpuLock(), world_dir=worlds
    )
    call(server.load_world("flat", 1, "fast"))
    with pytest.raises(server.SimStateError):
        call(server.spawn_robot(str(broken), server.Pose(), "r1"))


def test_the_same_seed_replays_the_same_conditions(lab: Path) -> None:
    first = run(lab, seed=7).randomization
    server.configure(reset_state=False, runner=FakeRunner())
    second = run(lab, seed=7).randomization
    assert first == second


def test_a_different_seed_gives_different_conditions(lab: Path) -> None:
    assert run(lab, seed=7).randomization != run(lab, seed=8, ns="r2").randomization


def test_the_values_reach_the_simulator_before_any_physics_runs(lab: Path) -> None:
    urdf = lab
    run(urdf)
    call(server.step(0.1))
    runner = server._S.runner
    assert isinstance(runner, FakeRunner)
    assert runner.ops.index("randomize") < runner.ops.index("step")
    applied = runner.payloads[runner.ops.index("randomize")]["req"]
    assert applied["ns"] == "r1"
    assert applied["surface_friction"] == pytest.approx(
        server._S.robots["r1"].randomization["surface_friction"]
    )


def test_the_record_travels_with_the_metrics(lab: Path) -> None:
    """T-037: the values are evidence for the run row, not debug output."""
    robot = run(lab)
    metrics = call(server.get_metrics(robot))
    assert metrics.randomization == robot.randomization


def test_sampled_friction_scales_every_mu_in_the_spawned_sdf() -> None:
    import xml.etree.ElementTree as ET

    rover = server.REPO_ROOT / "ros2_ws/src/neml_sim/models/test_rover.sdf"
    out = server._with_friction({"sdf_filename": str(rover), "friction": 0.77})
    assert out != str(rover)
    root = ET.parse(out).getroot()  # noqa: S314  # nosec B314 - file written by _with_friction
    mus = [float(e.text) for e in root.iter("mu") if e.text]
    assert mus and max(mus) == pytest.approx(1.1)  # 1.0 * 0.77 / 0.7
    assert server._with_friction({"sdf_filename": "x.urdf", "friction": 0.77}) == "x.urdf"


def test_friction_copy_keeps_relative_mesh_paths_pointing_home(tmp_path: Path) -> None:
    sdf = tmp_path / "m.sdf"
    sdf.write_text(
        "<sdf><model name='m'><link name='l'><collision name='c'><geometry>"
        "<mesh><uri>meshes/a.stl</uri></mesh></geometry><surface><friction><ode><mu>1</mu>"
        "</ode></friction></surface></collision></link></model></sdf>"
    )
    out = server._with_friction({"sdf_filename": str(sdf), "friction": 0.7})
    uri = next(server.ET.parse(out).getroot().iter("uri")).text  # noqa: S314
    assert Path(uri or "") == (tmp_path / "meshes" / "a.stl").resolve()
