# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""T-011: one unit test per prompt profile (SPEC 4.4). Schemas: test_schemas.py."""

from pathlib import Path

import pytest
import yaml

from neml_brain.llm.profiles import FAILURE_MODES, PROFILES, HumanText, Profile, check_failure_mode

REPO_ROOT = Path(__file__).resolve().parents[3]

# Owner decision 4 (amends SPEC 4.4), copied by hand like the table above.
DECIDED_MODES = [
    "joint_limit_hit",
    "torque_saturation",
    "balance_lost",
    "foot_slip",
    "collision",
    "goal_not_reached",
    "timeout",
    "sensor_dropout",
    "power_brownout",
    "unknown",
]

# SPEC 4.4 table, copied by hand. If the code drifts, this fails.
SPEC_TABLE = [
    ("router", 8, "guided_choice"),
    ("param_mech", 256, "guided_json"),
    ("param_elec", 256, "guided_json"),
    ("param_skill", 256, "guided_json"),
    ("failure_tag", 64, "guided_choice"),
    ("summarize", 384, "none"),
]


@pytest.mark.parametrize(("name", "max_tokens", "constraint"), SPEC_TABLE)
def test_profile_matches_the_spec_table(name, max_tokens, constraint):
    profile = PROFILES[name]
    assert (profile.max_tokens, profile.constraint) == (max_tokens, constraint)
    assert 0 < len(profile.system_prompt) < 400  # short, single job
    assert profile.system_prompt.isascii()  # English, no localisation drift


def test_there_are_exactly_six_profiles_and_only_summarize_is_free():
    assert [p.name for p in PROFILES.values()] == [n for n, _, _ in SPEC_TABLE]
    free = [p.name for p in PROFILES.values() if p.constraint == "none"]
    assert free == ["summarize"]


def test_a_second_unconstrained_profile_cannot_be_declared():
    with pytest.raises(ValueError, match="only the summarize profile"):
        Profile("param_mech", "anything", 256, "none")
    with pytest.raises(ValueError, match="only the summarize profile"):
        Profile("summarize", "anything", 384, "guided_json")
    with pytest.raises(ValueError):
        Profile("router", "anything", 8, "regex")


def test_profiles_are_frozen():
    with pytest.raises(AttributeError):  # dataclasses.FrozenInstanceError
        PROFILES["router"].max_tokens = 4096


def test_human_text_is_a_string_but_recognisable():
    text = HumanText("Rapor")
    assert isinstance(text, str) and text == "Rapor"
    assert not isinstance("Rapor", HumanText)


# --- SPEC 4.4 failure_tag choices (owner decision 4) ------------------------


def test_failure_tag_profile_carries_the_decided_choice_list():
    assert FAILURE_MODES == DECIDED_MODES
    assert PROFILES["failure_tag"].choices == tuple(DECIDED_MODES)


def test_unknown_is_in_the_list_on_purpose():
    """A closed enum with no escape hatch makes a 1.5B model force a wrong label."""
    assert "unknown" in FAILURE_MODES


@pytest.mark.parametrize("mode", DECIDED_MODES)
def test_every_decided_mode_is_accepted(mode):
    assert check_failure_mode(mode) == mode


@pytest.mark.parametrize("mode", ["joint_limit", "balance_loss", "JOINT_LIMIT_HIT", "", "hata"])
def test_anything_outside_the_list_is_refused(mode):
    with pytest.raises(ValueError, match="not a failure_tag mode"):
        check_failure_mode(mode)


def test_config_llm_yaml_mirrors_the_one_list():
    """The constraint has to be visible in config, and the mirror has to be true."""
    doc = yaml.safe_load((REPO_ROOT / "config" / "llm.yaml").read_text(encoding="utf-8"))
    assert doc["profiles"]["failure_tag"]["choices"] == FAILURE_MODES


def test_the_list_is_defined_exactly_once_in_the_tree():
    """This duplication already happened once: reflection.py invented its own ten.

    Anything that repeats the literal modes - a second FAILURE_MODES, an enum, a
    Literal[...] - shows up here. Importing the list is the only allowed way to
    use it; config/llm.yaml is the one declared mirror and is pinned equal above.
    """
    marker = "joint_limit_hit"
    sources = sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "brain" / "neml_brain").rglob("*.py")
        if marker in path.read_text(encoding="utf-8", errors="ignore")
    )
    assert sources == ["brain/neml_brain/llm/profiles.py"]

    mirrors = sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "config").rglob("*.yaml")
        if marker in path.read_text(encoding="utf-8", errors="ignore")
    )
    assert mirrors == ["config/llm.yaml"]
