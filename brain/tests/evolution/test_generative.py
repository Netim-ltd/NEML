# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Robots designed by the model: plan checks, URDF assembly, gates and the whole flow with fakes."""

from __future__ import annotations

import struct
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from neml_brain.evolution.generative import (
    Generator,
    check_plan,
    gate,
    layout_issues,
    model_name,
    urdf_of,
)
from neml_brain.evolution.judges import equip
from neml_brain.evolution.urdf_assembly import assemble
from neml_brain.learning.store import LearningStore

PLAN = {
    "name": "Bahçe Gezgini",
    "purpose": "bahçede dolaşan küçük gezgin",
    "links": [
        {
            "name": "base",
            "parent": "",
            "role": "gövde",
            "source": "designed",
            "material": "PETG",
            "dims_mm": [160, 100, 40],
            "mass_g": 400,
            "joint": {"type": "fixed", "x": 0, "y": 0, "z": 0, "axis": "z"},
        },
        {
            "name": "wheel_l",
            "parent": "base",
            "role": "sol tekerlek",
            "source": "bought",
            "part": "tt_wheel",
            "dims_mm": [60, 60, 20],
            "mass_g": 80,
            "joint": {
                "type": "revolute",
                "x": 0,
                "y": 60,
                "z": 0,
                "axis": "y",
                "lower_deg": -180,
                "upper_deg": 180,
            },
        },
        {
            "name": "wheel_r",
            "parent": "base",
            "role": "sağ tekerlek",
            "source": "bought",
            "part": "tt_wheel",
            "dims_mm": [60, 60, 20],
            "mass_g": 80,
            "joint": {
                "type": "revolute",
                "x": 0,
                "y": -60,
                "z": 0,
                "axis": "y",
                "lower_deg": -180,
                "upper_deg": 180,
            },
        },
    ],
}
RECIPE = {
    "solids": [{"id": "a", "t": "box", "at": [-80, -50, -20], "size": [160, 100, 40]}],
    "steps": [],
    "result": "a",
}


def test_a_plan_needs_one_root_known_parents_and_sane_mass():
    assert check_plan(dict(PLAN)) == []
    two_roots = {**PLAN, "links": [PLAN["links"][0], {**PLAN["links"][1], "parent": ""}]}
    assert any("kök" in p for p in check_plan(two_roots))
    orphan = {**PLAN, "links": [PLAN["links"][0], {**PLAN["links"][1], "parent": "nowhere"}]}
    assert any("önceden tanımlı değil" in p for p in check_plan(orphan))
    heavy = {
        **PLAN,
        "links": [{**PLAN["links"][0], "mass_g": 5000}] * 1
        + [{**PLAN["links"][1], "mass_g": 5000}] * 0,
    }
    assert check_plan({**PLAN, "links": [{**PLAN["links"][0], "mass_g": 1}]}) != []  # 1 g robot
    assert heavy["links"][0]["mass_g"] == 5000


def test_the_urdf_written_from_a_plan_is_read_by_the_same_assembler_as_imports():
    urdf = urdf_of(PLAN, {"base": "base.stl"})
    summary, found, rig, _ = assemble(urdf)
    assert {a["link"] for a in found} == {"base", "wheel_l", "wheel_r"}
    assert [j["name"] for j in rig["joints"]] == ["j_wheel_l", "j_wheel_r"] and rig["joints"][0][
        "type"
    ] == "revolute"
    assert any(a.get("mesh") == "base.stl" for a in found) and any(a.get("shape") for a in found)
    assert rig["links"]["base"]["mass"] == pytest.approx(0.4)


def test_the_gate_stops_a_beam_that_would_break_and_passes_a_sturdy_part():
    beam = {**PLAN, "links": [{**PLAN["links"][0], "dims_mm": [200, 10, 8], "mass_g": 3000}]}
    thin = {"base": {"bbox": [0, 0, 0, 200, 10, 2], "volume_mm3": 200 * 10 * 2 * 0.5}}
    assert any("emniyet" in p for p in gate(beam, thin))
    block = {"base": {"bbox": [0, 0, 0, 160, 100, 40], "volume_mm3": 160 * 100 * 40 * 0.3}}
    assert gate(PLAN, block) == []


class Llm:
    def __init__(self):
        self.calls = []

    async def fill(self, prompt, schema, profile="x", max_tokens=None):
        self.calls.append(prompt[:30])
        if "Bir robot tasarla" in prompt:
            root, *kids = PLAN["links"]
            return {
                "name": PLAN["name"],
                "purpose": PLAN["purpose"],
                "root": {k: v for k, v in root.items() if k not in ("parent", "joint")},
                "links": kids,
            }
        return RECIPE


class Mcp:
    def __init__(self, tmp):
        self.tmp, self.fail_first = tmp, True

    async def call(self, server, tool, args, timeout=0):
        assert (server, tool) == ("freecad", "build_recipe")
        if self.fail_first:
            self.fail_first = False
            raise RuntimeError("result is not a valid solid")
        stl = Path(args["out_dir"]) / f"{args['name']}.stl"
        stl.write_bytes(b"\0" * 80 + struct.pack("<I", 0))
        step = stl.with_suffix(".step")
        step.write_text("step")
        return {
            "volume_mm3": 160 * 100 * 40 * 0.3,
            "bbox": [-80, -50, -20, 80, 50, 20],
            "stl": str(stl),
            "step": str(step),
            "center_of_mass": [0, 0, 0],
        }


class Uploader:
    async def upload(self, path, kind, name=None):
        return f"/api/v1/media/{kind}"


class Runner:
    def __init__(self):
        self.published = []

    async def active_genome(self):
        return {
            "id": "seed@1",
            "name": "quadruped_v2",
            "version": 1,
            "body": {"morphology": {"body_type": "legged"}, "mechanical": {"body_mass_kg": 2.4}},
        }

    async def _new_genome(self, session, parent, body, status):
        self.body = body
        return "bahce_gezgini@abc", body

    async def _publish_scene(self, gid, body):
        self.published.append(gid)


class Importer:
    def __init__(self):
        self.runner, self._uploader = Runner(), Uploader()

    async def _mesh(self, path, kind, work):
        return {
            "urls": {"stl": "/api/v1/media/stl"},
            "size": [160.0, 100.0, 40.0],
            "center": [0.0, 0.0, 0.0],
        }

    async def _free_name(self, name):
        return name


class Session:
    def __init__(self):
        self.sql = []

    async def execute(self, statement, params=None):
        self.sql.append(str(statement)[:40])

    async def commit(self):
        pass


@pytest.mark.asyncio
async def test_the_whole_design_flow_retries_a_failed_part_stores_a_draft_and_activates_it(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("neml_brain.evolution.generative.robot_issues", lambda plan: [])  # the flow is tested here, the robot judge in test_judges
    session = Session()

    @asynccontextmanager
    async def sessions():
        yield session

    importer = Importer()
    store = LearningStore(tmp_path / "learning")
    gen = Generator(Mcp(tmp_path), importer, sessions, Llm(), store, tmp_path / "gen")
    steps = []
    out = await gen.design("bahçede dolaşan robot", "owner", steps.append)
    assert out["model"] == "bahce_gezgini" and out["activated"] and out["problems"] == []
    assert any(
        "parça tarifi 2" in s for s in steps
    )  # the first build failed and the model was asked again
    assert any("UPDATE genomes SET status = 'active'" in q for q in session.sql)
    entries = importer.runner.body["mechanical"]["imports"]
    assert {e["kind"] for e in entries} == {"stl", "urdf"} and entries[0]["design"][
        "recipe"
    ] == RECIPE
    assert importer.runner.body["mechanical"]["generated"][
        "by"
    ] == "owner" and importer.runner.published == ["bahce_gezgini@abc"]
    off = Generator(Mcp(tmp_path), Importer(), sessions, Llm(), store, tmp_path / "gen")
    assert (await off.design("x", "owner", auto_activate=False))[
        "activated"
    ] is False  # left as a draft when auto-activation is off


def test_model_names_fold_turkish_letters():
    assert model_name("Bahçe Robotu!") == "bahce_robotu"


def _with_y(*ys):
    kids = [
        {**PLAN["links"][i + 1], "joint": {**PLAN["links"][i + 1]["joint"], "y": y}}
        for i, y in enumerate(ys)
    ]
    return {**PLAN, "links": [PLAN["links"][0], *kids]}


def test_the_layout_critic_finds_overlaps_and_floating_parts():
    assert any("iç içe" in i for i in layout_issues(_with_y(0, 0)))  # both wheels in the same place
    assert any("değmiyor" in i for i in layout_issues(_with_y(400)))  # floating away from the body
    assert layout_issues(_with_y(70, -70)) == []  # one on each side, touching the body


@pytest.mark.asyncio
async def test_a_restarted_design_reuses_its_plan_and_the_parts_already_built(tmp_path):
    @asynccontextmanager
    async def sessions():
        yield Session()

    llm = Llm()
    gen = Generator(Mcp(tmp_path), Importer(), sessions, llm, LearningStore(tmp_path / "l"), tmp_path / "gen")
    ckpt = {"plan": equip(PLAN), "out": "abc", "built": {}}  # a stored plan went through equip() in _plan
    saved = []
    out = await gen.design("x", "owner", ckpt=ckpt, save=lambda: saved.append(len(ckpt["built"])))
    assert out["model"] == "bahce_gezgini"
    assert not any("Bir robot tasarla" in c for c in llm.calls)  # no new plan
    assert saved and ckpt["built"]  # each built part was checkpointed


def test_a_low_wide_plan_outscores_a_tall_narrow_one():
    from neml_brain.evolution.generative import plan_score

    squat = _with_y(70, -70)
    tall = {**squat, "links": [{**squat["links"][0], "dims_mm": [40, 40, 400]}, *squat["links"][1:]]}
    assert plan_score(squat)[0] > plan_score(tall)[0]


@pytest.mark.asyncio
async def test_a_race_builds_the_plan_with_fewest_problems(tmp_path):
    answers = iter([_with_y(0, 0), _with_y(70, -70), _with_y(0, 0)])  # only the second plan has no overlap

    class RaceLlm:
        async def fill(self, prompt, schema, profile="x", max_tokens=None):
            plan = next(answers)
            root, *kids = plan["links"]
            return {"name": plan["name"], "purpose": "p", "root": {k: v for k, v in root.items() if k not in ("parent", "joint")}, "links": kids}

    gen = Generator(Mcp(tmp_path), Importer(), None, RaceLlm(), LearningStore(tmp_path / "l"), tmp_path / "gen")
    gen.variants = 3
    seen: list[str] = []
    won = await gen._race("x", seen.append)  # noqa: SLF001
    assert layout_issues(won) == [] and any("kazanan" in s for s in seen)


def test_the_layout_solver_separates_links_that_sit_in_each_other():
    from neml_brain.evolution.generative import repair_layout

    stacked = _with_y(0, 0)  # both wheels inside the body and in each other
    assert layout_issues(stacked)
    assert layout_issues(repair_layout(stacked)) == []
    assert repair_layout(PLAN)["links"][0] == PLAN["links"][0]
