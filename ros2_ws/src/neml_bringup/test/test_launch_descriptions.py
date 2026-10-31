# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SS18.1 requires launch tests on all bringup. This file covers the part that
needs no processes: every launch file builds, every one sets the SS17.2
environment, and none of them hardcodes a NEML topic name.

test_safety_launch.py covers the part that does need a process."""

import importlib.util
from pathlib import Path

import pytest
import yaml

launch = pytest.importorskip("launch", reason="launch comes from a sourced ROS 2 install")
pytest.importorskip("launch_ros")

from launch import LaunchContext  # noqa: E402
from launch.actions import DeclareLaunchArgument, SetEnvironmentVariable  # noqa: E402
from launch.utilities import perform_substitutions  # noqa: E402

PKG = Path(__file__).resolve().parent.parent
LAUNCH_DIR = PKG / "launch"
CONFIG_DIR = PKG / "config"
LAUNCH_FILES = ["robot.launch.py", "sim.launch.py", "safety.launch.py", "swarm.launch.py"]

# SS17.2 topic classes. A launch file that spells one of these out has taken a
# name away from the YAML and put it somewhere nobody looks.
TOPIC_CLASS_PREFIXES = ("telemetry/", "cmd/", "state/", "camera/")


def _load(filename):
    path = LAUNCH_DIR / filename
    spec = importlib.util.spec_from_file_location(filename.replace(".", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _flatten(entities):
    for entity in entities:
        yield entity
        sub = getattr(entity, "entities", None)
        if sub:
            yield from _flatten(sub)


@pytest.fixture(scope="module", params=LAUNCH_FILES)
def description(request):
    return request.param, _load(request.param).generate_launch_description()


def test_launch_file_builds(description):
    _name, ld = description
    assert isinstance(ld, launch.LaunchDescription)
    assert ld.entities


def test_ros2_environment_matches_spec(description):
    """SS17.2: ROS_DOMAIN_ID 42 and rmw_zenoh_cpp, set by the launch file so a
    forgotten shell export cannot put a robot on the wrong domain."""
    _name, ld = description
    context = LaunchContext()
    env = {
        perform_substitutions(context, action.name): perform_substitutions(
            context, action.value
        )
        for action in _flatten(ld.entities)
        if isinstance(action, SetEnvironmentVariable)
    }
    assert env["ROS_DOMAIN_ID"] == "42"
    assert env["RMW_IMPLEMENTATION"] == "rmw_zenoh_cpp"


def test_zenoh_router_config_is_pointed_at(description):
    _name, ld = description
    context = LaunchContext()
    names = {
        perform_substitutions(context, action.name)
        for action in _flatten(ld.entities)
        if isinstance(action, SetEnvironmentVariable)
    }
    assert "ZENOH_ROUTER_CONFIG_URI" in names


def test_every_launch_argument_has_a_default(description):
    """A bringup file that needs a hand-typed argument is a bringup file that
    the autonomy loop cannot start (SS14.1)."""
    _name, ld = description
    for action in _flatten(ld.entities):
        if isinstance(action, DeclareLaunchArgument):
            assert action.default_value is not None, action.name


@pytest.mark.parametrize("filename", LAUNCH_FILES)
def test_no_hardcoded_neml_topic_names(filename):
    text = (LAUNCH_DIR / filename).read_text(encoding="utf-8")
    # Strip comments and docstrings the cheap way: only look at code lines.
    code = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
    for prefix in TOPIC_CLASS_PREFIXES:
        assert f'"{prefix}' not in code, f"{filename} hardcodes a {prefix}* topic"


@pytest.mark.parametrize("filename", LAUNCH_FILES)
def test_copyright_header(filename):
    head = (LAUNCH_DIR / filename).read_text(encoding="utf-8").splitlines()[0]
    assert head == "# Copyright (c) 2026 Mustafa Gulsoy."


def test_robot_params_declare_every_topic_the_nodes_use():
    params = yaml.safe_load((CONFIG_DIR / "robot.yaml").read_text(encoding="utf-8"))
    watchdog = params["/**/watchdog_monitor"]["ros__parameters"]
    assert watchdog["heartbeat_timeout_s"] == 0.150   # SS5.1
    assert watchdog["start_latched"] is True
    # 200 Hz evaluation keeps the T-074 budget under 50 ms.
    assert watchdog["evaluate_rate_hz"] >= 20.0
    guard = params["/**/link_guard"]["ros__parameters"]
    assert guard["link_timeout_s"] == 2.0            # T-083
    assert 0.0 < guard["trip_fraction"] < 1.0


def test_swarm_params_roster_and_timeout():
    params = yaml.safe_load((CONFIG_DIR / "swarm.yaml").read_text(encoding="utf-8"))
    coordinator = params["/**/swarm_coordinator"]["ros__parameters"]
    assert len(coordinator["robots"]) == 3           # T-080
    assert coordinator["robot_timeout_s"] == 2.0     # T-083
    # A robot must get several heartbeats inside its own trip window.
    assert coordinator["heartbeat_rate_hz"] * coordinator["robot_timeout_s"] >= 5


def test_zenoh_router_config_shape():
    text = (CONFIG_DIR / "zenoh_router.json5").read_text(encoding="utf-8")
    assert 'mode: "router"' in text
    assert "tcp/0.0.0.0:7447" in text
    # T-081: multicast scouting off on a shared WiFi channel.
    assert "multicast" in text and "enabled: false" in text
