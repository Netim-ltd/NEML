# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Guards the neml_msgs contract: the exact interface set of NEML_SPEC.md SS15
and the rule that every field carries a unit/meaning comment."""

from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parent.parent

EXPECTED = [
    "msg/RobotState.msg",
    "msg/SafetyStatus.msg",
    "msg/JointTelemetry.msg",
    "msg/BatteryState.msg",
    "srv/SetDeploymentLevel.srv",
    "srv/RunSelfTest.srv",
    "action/ExecuteSkill.action",
    "action/RunManoeuvre.action",
]


def _field_lines(text):
    """Yield (lineno, line) for declaration lines, skipping comments, blanks
    and the ---/=== section separators."""
    for i, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#") or set(line) == {"-"}:
            continue
        yield i, raw


def test_exact_interface_set():
    """No interface beyond the eight the spec names, none missing."""
    on_disk = sorted(
        f"{d}/{p.name}"
        for d in ("msg", "srv", "action")
        for p in (PKG / d).iterdir()
    )
    assert on_disk == sorted(EXPECTED)


@pytest.mark.parametrize("rel", EXPECTED)
def test_every_field_is_documented(rel):
    """Constants may stand alone; every field needs a trailing comment naming
    its unit or meaning (SS15 "SI birimleri", task contract)."""
    text = (PKG / rel).read_text(encoding="utf-8")
    for lineno, line in _field_lines(text):
        is_constant = "=" in line.split("#")[0]
        if is_constant:
            continue
        assert "#" in line, f"{rel}:{lineno} undocumented field: {line.strip()}"
        assert line.split("#", 1)[1].strip(), f"{rel}:{lineno} empty comment"


@pytest.mark.parametrize("rel", EXPECTED)
def test_copyright_header(rel):
    head = (PKG / rel).read_text(encoding="utf-8").splitlines()[0]
    assert head == "# Copyright (c) 2026 Mustafa Gulsoy."


def test_no_bare_float32_or_int_units():
    """SI doubles everywhere: a float32 in a physical field loses resolution on
    1 kHz torque telemetry. Catch a regression to float32."""
    for rel in EXPECTED:
        text = (PKG / rel).read_text(encoding="utf-8")
        for lineno, line in _field_lines(text):
            assert not line.strip().startswith("float32"), f"{rel}:{lineno} use float64"
