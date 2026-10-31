# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for neml-mcp-cad (SPEC 6.2 #13): declarative CSG recipes, no templates.

FreeCAD is LGPL and stays outside this tree (SPEC 1.3): the only thing this
server may do is hand a driver script to `freecadcmd` as a separate process.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from mcp_servers.neml_mcp_cad import server


def call(coro: Any) -> Any:
    return asyncio.run(coro)


class FakeFreecad:
    """Stands in for freecadcmd: reads the request, writes the result JSON."""

    def __init__(self, result: dict[str, Any] | None = None, raises: Exception | None = None):
        self.result = result
        self.raises = raises
        self.calls: list[list[str]] = []

    async def __call__(self, argv: list[str], timeout_s: float) -> str:
        self.calls.append(argv)
        if self.raises is not None:
            raise self.raises
        request = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
        if self.result is not None:
            Path(request["result_path"]).write_text(json.dumps(self.result), encoding="utf-8")
        return ""


def test_the_cad_server_offers_recipes_drawings_standards_assemblies_and_checks() -> None:
    assert sorted(server.TOOLS) == ["assemble", "build_recipe", "convert", "drawing", "fem", "fit", "standard_part"]


def test_freecad_failures_and_missing_results_come_back_as_cad_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "ALLOWED_ROOTS", (tmp_path.resolve(),))
    out = str(tmp_path / "x")
    server.configure(runner=FakeFreecad(result=None))
    with pytest.raises(server.CadError, match="no result"):
        call(server.build_recipe(GOOD_RECIPE, out, "part"))
    server.configure(runner=FakeFreecad(result={"error": "result is 2 separate solids"}))
    with pytest.raises(server.CadError, match="separate solids"):
        call(server.build_recipe(GOOD_RECIPE, out, "part"))


GOOD_RECIPE = {
    "solids": [
        {"id": "a", "t": "box", "size": [40, 20, 10], "at": [0, 0, 0]},
        {"id": "h", "t": "cyl", "r": 1.6, "h": 12, "axis": "z", "at": [5, 10, -1]},
    ],
    "steps": [{"op": "cut", "a": "a", "b": "h", "out": "p"}],
    "result": "p",
}


def test_a_design_recipe_is_data_and_only_boxes_cylinders_spheres_with_cut_fuse() -> None:
    server.check_recipe(GOOD_RECIPE)
    server.check_recipe({**GOOD_RECIPE, "round": {"kind": "chamfer", "r": 1.5, "edges": "top"}})
    bad = [
        {**GOOD_RECIPE, "result": "nope"},
        {**GOOD_RECIPE, "solids": [{"id": "a", "t": "mesh", "at": [0, 0, 0]}]},
        {**GOOD_RECIPE, "solids": [{"id": "a", "t": "box", "size": [4000, 1, 1], "at": [0, 0, 0]}]},
        {**GOOD_RECIPE, "steps": [{"op": "exec", "a": "a", "b": "h", "out": "p"}]},
        {"solids": [], "result": "x"},
        {**GOOD_RECIPE, "round": {"kind": "fillet", "r": 2, "edges": "everything"}},
        {**GOOD_RECIPE, "round": {"kind": "melt", "r": 2, "edges": "all"}},
        {**GOOD_RECIPE, "round": {"kind": "fillet", "r": "__import__('os')", "edges": "all"}},
        {**GOOD_RECIPE, "solids": [{"id": "a", "t": "box", "size": ["__import__('os')", 1, 1], "at": [0, 0, 0]}]},
    ]
    for recipe in bad:
        with pytest.raises(server.CadError):
            server.check_recipe(recipe)


def test_build_recipe_runs_freecad_with_the_validated_recipe_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "Path", Path)
    runner = FakeFreecad(result={"volume_mm3": 7.0, "stl": "x.stl"})
    server.configure(runner=runner)
    with pytest.raises(server.CadError):  # outside /srv/neml
        call(server.build_recipe(GOOD_RECIPE, str(tmp_path), "part"))
    with pytest.raises(server.CadError):
        call(server.build_recipe(GOOD_RECIPE, "/srv/neml/work/x", "../evil"))
    assert runner.calls == []


def test_a_recipe_with_a_typo_is_mended_not_lost():
    broken = {
        "solids": [{"id": "a", "t": "box", "size": [10, 10, 10], "at": [0, 0, 0]}, {"id": "a", "t": "cyl", "r": 2, "h": 12, "axis": "z", "at": [5, 5, -1]}],
        "steps": [{"op": "cut", "a": "a", "b": "ghost", "out": "x"}, {"op": "cut", "a": "a", "b": "s1_1", "out": "y"}],
        "result": "nope",
    }
    fixed = server.repair_recipe(broken)
    server.check_recipe(fixed)
    assert [s["op"] for s in fixed["steps"]] == ["cut"] and fixed["result"] == "y"
