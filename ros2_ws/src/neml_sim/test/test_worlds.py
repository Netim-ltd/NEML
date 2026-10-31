# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The SS11.1 physics contract, checked against the world files themselves.

These five numbers decide whether a sim run is comparable to any other sim run
and to hardware. A pull request that quietly relaxes max_step_size to make a
regression pass fails here instead of six weeks later in the reality gap."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

WORLDS_DIR = Path(__file__).resolve().parent.parent / "worlds"
WORLDS = ["flat", "obstacle_low", "ramp_10deg", "rough_terrain", "maze"]


@pytest.fixture(scope="module", params=WORLDS)
def world(request):
    path = WORLDS_DIR / f"{request.param}.sdf"
    return request.param, ET.parse(path).getroot().find("world")


def test_exactly_the_five_spec_worlds():
    assert sorted(p.stem for p in WORLDS_DIR.glob("*.sdf")) == sorted(WORLDS)


def test_world_name_matches_file_name(world):
    name, root = world
    assert root.get("name") == name


def test_dart_at_one_millisecond_as_fast_as_possible(world):
    _name, root = world
    physics = root.find("physics")
    assert physics is not None
    assert physics.get("type") == "dart"
    assert float(physics.find("max_step_size").text) == pytest.approx(0.001)
    assert float(physics.find("real_time_factor").text) == pytest.approx(0.0)


def test_dartsim_engine_plugin_is_explicit(world):
    """`type="dart"` alone is a hint; the physics system plugin is what
    actually selects the engine."""
    _name, root = world
    engines = [
        p.find("engine/filename").text
        for p in root.findall("plugin")
        if p.find("engine/filename") is not None
    ]
    assert engines == ["gz-physics-dartsim-plugin"]


def test_sensor_and_contact_systems_are_loaded(world):
    """T-034: sensor data has to reach ROS 2. No Sensors system, no camera."""
    _name, root = world
    filenames = {p.get("filename") for p in root.findall("plugin")}
    assert {
        "gz-sim-physics-system",
        "gz-sim-scene-broadcaster-system",
        "gz-sim-sensors-system",
        "gz-sim-imu-system",
        "gz-sim-contact-system",
        # The only publisher of /world/<world>/model/<ns>/joint_state, which is
        # the encoder half of config/gz_bridge.yaml. Without it that bridge
        # entry carries nothing and the absence is silent.
        "gz-sim-joint-state-publisher-system",
    } <= filenames


def test_nothing_is_fetched_from_fuel(world):
    """SS11.2: a world that downloads a model is a world whose sha256 does not
    describe what was simulated."""
    name, _root = world
    text = (WORLDS_DIR / f"{name}.sdf").read_text(encoding="utf-8")
    assert "fuel.gazebosim" not in text
    assert "<uri>" not in text


def test_ground_friction_is_the_nominal_value(world):
    """SS11.4 nominal 0.7. Randomisation is the runner's job, not the file's."""
    _name, root = world
    mu = root.find("model[@name='ground_plane']/link/collision/surface/friction/ode/mu")
    assert float(mu.text) == pytest.approx(0.7)


def test_obstacle_low_has_the_forty_millimetre_step():
    """M3_step is defined as a 40 mm step (SS11.3); the world must contain one."""
    root = ET.parse(WORLDS_DIR / "obstacle_low.sdf").getroot().find("world")
    heights = {
        float(box.text.split()[2])
        for box in root.findall("model/link/collision/geometry/box/size")
    }
    assert 0.040 in heights


def test_ramp_is_ten_degrees():
    root = ET.parse(WORLDS_DIR / "ramp_10deg.sdf").getroot().find("world")
    pose = root.find("model[@name='ramp']/pose").text.split()
    pitch_deg = abs(float(pose[4])) * 180.0 / 3.141592653589793
    assert pitch_deg == pytest.approx(10.0, abs=0.01)


def test_rough_terrain_relief_is_within_the_declared_band():
    root = ET.parse(WORLDS_DIR / "rough_terrain.sdf").getroot().find("world")
    heights = [
        float(box.text.split()[2])
        for model in root.findall("model")
        if model.get("name", "").startswith("tile_")
        for box in model.findall("link/collision/geometry/box/size")
    ]
    assert len(heights) == 72
    assert 0.005 <= min(heights) and max(heights) <= 0.045


def test_maze_is_closed():
    root = ET.parse(WORLDS_DIR / "maze.sdf").getroot().find("world")
    names = {m.get("name") for m in root.findall("model")}
    assert {"outer_n", "outer_s", "outer_e", "outer_w"} <= names


def test_copyright_header_present():
    for name in WORLDS:
        text = (WORLDS_DIR / f"{name}.sdf").read_text(encoding="utf-8")
        assert "Copyright (c) 2026 Mustafa Gulsoy." in text
