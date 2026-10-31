# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Real FreeCAD / KiCad runs (integration: skipped when the tool is not installed).

pytest -m integration mcp_servers/tests/test_tool_integration.py
"""

import asyncio
import shutil
from pathlib import Path

import pytest

from mcp_servers.neml_mcp_cad import server as cad
from mcp_servers.neml_mcp_kicad import server as kicad
from mcp_servers.tests.test_kicad_platform import CIRCUIT

pytestmark = pytest.mark.integration


@pytest.mark.skipif(shutil.which("freecadcmd") is None, reason="needs freecadcmd")
def test_a_cad_recipe_builds_a_solid_with_step_and_stl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cad, "ALLOWED_ROOTS", (tmp_path.resolve(),))
    recipe = {
        "solids": [
            {"id": "a", "t": "box", "at": [0, 0, 0], "size": [40, 20, 10]},
            {"id": "h", "t": "cyl", "r": 1.6, "h": 12, "axis": "z", "at": [5, 10, -1]},
        ],
        "steps": [{"op": "cut", "a": "a", "b": "h", "out": "p"}],
        "result": "p",
    }

    async def go() -> None:
        built = await cad.build_recipe(recipe, str(tmp_path / "out"), "plate", 300)
        assert built["volume_mm3"] > 0 and Path(built["stl"]).is_file() and Path(built["step"]).is_file()

    asyncio.run(go())


@pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="needs kicad-cli")
def test_a_routed_circuit_loads_and_has_no_error_level_violations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEML_ARTIFACT_DIR", str(tmp_path))

    async def go() -> None:
        made = await kicad.build_circuit(CIRCUIT, str(tmp_path / "board"), "demo")
        drc = await kicad.run_drc(made["board"])
        erc = await kicad.run_erc(made["schematic"])
        assert drc["passed"] and erc["passed"]

    asyncio.run(go())
