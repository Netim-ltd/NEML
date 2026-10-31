# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The viewer's screw plan (fasteners.js), run with node."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from neml_brain.paths import REPO_ROOT


def test_the_screw_plan_names_what_goes_where(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    js = (REPO_ROOT / "dotnet" / "Neml.Web" / "wwwroot" / "js" / "fasteners.js").as_uri()
    script = tmp_path / "run.mjs"
    script.write_text(
        f"import {{ fastenerPlan }} from {js!r};\n"
        "const box = (id, pos, size, group = 'x') => ({ id, group, pos, geom: { size } });\n"
        "const a = fastenerPlan({ parts: [box('shell_lower', [0, 0, -20], [200, 100, 40]), box('shell_upper', [0, 0, 20], [200, 100, 40]), box('board_plate', [55, 0, 5], [95, 66, 3])] });\n"
        "const rig = { joints: [{ name: 'j', type: 'fixed', parent: 'a', child: 'b', pos: [0, 0, 35], quat: [0, 0, 0, 1], axis: [1, 0, 0], lower: 0, upper: 0 }], links: {} };\n"
        "const b = fastenerPlan({ parts: [], rig });\n"
        "process.stdout.write(JSON.stringify({ a, b }));\n",
        encoding="utf-8",
    )
    out = subprocess.run(  # noqa: S603 - node runs a script this test wrote
        [node, str(script)], capture_output=True, text=True, check=True, timeout=60
    )
    got = json.loads(out.stdout)
    assert [(f["part"], f["host"], f["qty"]) for f in got["a"]] == [
        ("shell_upper", "shell_lower", 4),
        ("board_plate", "shell_lower", 4),
    ]
    assert got["b"][0]["at"] == [[0, 0, 35]] and got["b"][0]["host"] == "a"
