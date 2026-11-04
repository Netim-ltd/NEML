# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""build123d scripts: refused unless plain geometry, run in a limited process."""

import importlib.util

import pytest

from mcp_servers.neml_mcp_cad.script import ScriptError, check_script, run_script

GOOD = "with BuildPart() as p:\n    Box(40, 20, 10)\nresult = p.part\n"


@pytest.mark.parametrize(
    "src, why",
    [
        ("import os\nresult = 1", "import yasak"),
        ("from subprocess import run\nresult = 1", "import yasak"),
        ("open('/etc/passwd').read()", "yasak ad: open"),
        ("x = ().__class__.__bases__", "alt çizgi"),
        ("eval('1')", "yasak ad: eval"),
        ("result = (", "sözdizimi"),
        ("", "boş"),
    ],
)
def test_dangerous_or_broken_scripts_are_refused_with_a_reason(src, why):
    with pytest.raises(ScriptError, match=why):
        check_script(src)


def test_plain_geometry_passes_the_check():
    check_script("from build123d import *\nimport math\n" + GOOD)


@pytest.mark.skipif(importlib.util.find_spec("build123d") is None, reason="build123d is installed in the CAD image only")
async def test_a_script_builds_a_part_with_measurements(tmp_path):
    out = await run_script(GOOD + "result = result - Cylinder(1.6, 10)\n", str(tmp_path), "kutu")
    assert out["volume_mm3"] == pytest.approx(8000 - 3.14159265 * 1.6**2 * 10, rel=1e-3)
    assert out["bbox"][3] - out["bbox"][0] == pytest.approx(40)
    assert (tmp_path / "kutu.stl").exists() and (tmp_path / "kutu.step").exists()


@pytest.mark.skipif(importlib.util.find_spec("build123d") is None, reason="build123d is installed in the CAD image only")
async def test_a_runaway_script_is_killed(tmp_path):
    with pytest.raises(ScriptError, match="bitmedi"):
        await run_script("while True:\n    pass\nresult = 1\n", str(tmp_path), "dongu", timeout_s=3)


@pytest.mark.skipif(importlib.util.find_spec("build123d") is None, reason="build123d is installed in the CAD image only")
async def test_math_names_are_ready_without_a_prefix(tmp_path):
    out = await run_script("result = Pos(30 * cos(pi / 2), 30 * sin(pi / 2), 0) * Box(10, 10, 10)\n", str(tmp_path), "yay")
    assert out["bbox"][4] == pytest.approx(35)
