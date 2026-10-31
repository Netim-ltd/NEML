# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Self-designed worlds, the structural analyst and the critic/engineer roles."""

from __future__ import annotations

import pytest

from neml_brain.evolution import structure
from neml_brain.evolution.worlds import TEMPLATES, WorldStore, box, check, reachable, render
from neml_brain.learning.roles import apply_accepted, audit
from neml_brain.learning.store import LearningStore


def test_every_template_at_every_difficulty_makes_a_valid_walkable_world(tmp_path):
    store = WorldStore(tmp_path)
    for template in TEMPLATES:
        for level in range(1, 7):
            got = store.create(template, level)
            assert got["ok"], got
            text = (tmp_path / f"{got['name']}.sdf").read_text(encoding="utf-8")
            assert "gz-physics-dartsim-plugin" in text and "<max_step_size>0.001" in text
    assert len(store.names()) == 5 + 18


def test_a_blocked_world_is_refused_and_never_written(tmp_path):
    wall = [box("wall", 1.5, 0.0, 0.5, 0.2, 6.0)]  # a tall wall across the whole lane
    assert not reachable(wall)
    sdf = render("w", wall, {"ground": "0.3 0.3 0.3 1", "mu": 0.7})
    assert "hedefe giden yürünebilir yol yok" in check(sdf, "w", wall)
    assert check(sdf.replace("<max_step_size>0.001", "<max_step_size>0.01"), "w") != []
    assert check(sdf, "other") != []  # the name must match the file
    assert (
        check(
            render("w", [box("low", 1.5, 0.0, 0.02, 0.2, 6.0)], {"ground": "g", "mu": 0.7}),
            "w",
            [box("low", 1.5, 0.0, 0.02, 0.2, 6.0)],
        )
        == []
    )  # a low step is walkable


def test_a_mastered_world_leads_to_a_harder_one(tmp_path):
    store = WorldStore(tmp_path)
    first = store.next_harder("flat")
    assert first and first["name"].endswith("_d1_s0")
    second = store.next_harder(first["name"])
    assert (
        second and second["name"].endswith("_d2_s0") and store.next_harder(first["name"]) is None
    )  # no duplicates


def _designed(size, volume, material="PETG"):
    return {
        "mechanical": {
            "body_mass_kg": 2.4,
            "imports": [
                {
                    "kind": "stl",
                    "name": "leg",
                    "size": size,
                    "design": {"volume_mm3": volume, "material": material},
                }
            ],
        }
    }


def test_the_structure_analyst_finds_a_weak_beam_and_stays_quiet_for_a_sturdy_part():
    weak = _designed([170, 14, 14], 170 * 14 * 14 * 0.2, "PLA")  # a thin hollow bar
    texts = " ".join(f["text"] for f in structure.analyze(weak))
    assert "emniyet katsayısı" in texts and texts.startswith("leg:")
    assert structure.analyze(_designed([100, 40, 30], 100 * 40 * 30 * 0.8, "PA6-CF")) == []
    assert (
        structure.analyze(_designed([60, 60, 20], 60 * 60 * 20 * 0.3)) == []
    )  # a plate is not a beam
    assert structure.analyze({"mechanical": {"imports": []}}) == []


WEAK = _designed([170, 14, 14], 170 * 14 * 14 * 0.2, "PLA")


class Critic:
    async def fill(self, prompt, schema, profile="x"):
        return {"verdict": "riskli", "risks": ["tork"], "verify_first": "servo torku"}


@pytest.mark.asyncio
async def test_roles_audit_once_review_and_apply_only_safe_remedies(tmp_path):
    store = LearningStore(tmp_path / "learning")
    worlds = WorldStore(tmp_path / "worlds")
    out = await audit(store, Critic(), WEAK, "quadruped_v2")
    assert out["review_structure"]["verdict"] == "riskli" and store.events()
    count = len(store.events())
    await audit(store, Critic(), WEAK, "quadruped_v2")
    assert len(store.events()) == count  # a finding is noted once, not every audit
    store.save_lessons(
        {
            "a": {
                "id": "a",
                "fp": "x",
                "domain": "world",
                "status": "accepted",
                "call": {
                    "name": "add_world",
                    "arguments": {"template": "hobby_garden", "difficulty": 1},
                },
            },
            "b": {
                "id": "b",
                "fp": "y",
                "domain": "structure",
                "status": "accepted",
                "call": {
                    "name": "thicken_wall",
                    "arguments": {"part": "leg_link", "wall_mm": 3},
                },
            },
        }
    )
    done = apply_accepted(store, worlds)
    assert len(done) == 2 and "hobby_garden_d1_s0" in worlds.index()
    lessons = store.lessons()
    assert (
        lessons["b"]["applied"] == "yalnızca öneri"
    )  # a design change is never carried out by the lab itself
    assert apply_accepted(store, worlds) == []  # and nothing runs twice


class Talker:
    """A model whose six specialists all want a sensor, so the lesson is accepted; the moderator also asks for research."""

    async def fill(self, prompt, schema, profile="x", max_tokens=None):
        if "moderatörüsün" in prompt:
            return {
                "verdict": "eksikleri var",
                "summary": "sensör yok",
                "how_it_should_work": "engeli görüp durmalı",
                "missing": ["mesafe sensörü"],
                "research_topics": ["bahçe robotu engel algılama"],
                "actions": [
                    {"kind": "add_sensor", "argument": "mesafe", "reason": "engel algılamıyor"},
                    {"kind": "fix_layout", "argument": "base", "reason": "tek oy"},
                ],
            }
        return {
            "findings": ["x"],
            "missing": ["sensör"],
            "suggest": "add_sensor",
            "argument": "mesafe",
            "objection": "",
            "message": "Sensör eksik, ben ekleyelim derim.",
        }


class Researcher:
    def __init__(self):
        self.topics = []

    async def learn(self, topic):
        self.topics.append(topic)
        return {"notes": [{"id": 1}]}


@pytest.mark.asyncio
async def test_the_round_table_turns_a_discussion_into_lessons_notes_and_the_next_brief(tmp_path):
    from contextlib import asynccontextmanager

    from neml_brain.learning.roundtable import RoundTable, next_brief, summarize

    class Row:
        def first(self):
            return [
                {
                    "genome_id": "bahce",
                    "mechanical": {
                        "body_mass_kg": 1,
                        "generated": {"purpose": "gezgin", "brief": "b"},
                        "imports": [],
                    },
                }
            ]

    class Session:
        async def execute(self, *a, **k):
            return Row()

    @asynccontextmanager
    async def sessions():
        yield Session()

    store = LearningStore(tmp_path / "learning")
    researcher = Researcher()
    table = RoundTable(Talker(), store, researcher, sessions)
    result = await table.review("bahce")
    assert result["verdict"] == "eksikleri var" and result["votes"] == {"add_sensor": 6}
    assert [m["role"] for m in result["chat"]][-1] == "moderator" and len(result["chat"]) == 13
    by_kind = {x["call"]["name"]: x for x in store.lessons().values()}
    assert (
        by_kind["add_sensor"]["status"] == "accepted"
        and by_kind["fix_layout"]["status"] == "proposed"
    )  # three votes decide
    assert researcher.topics == ["bahçe robotu engel algılama"] and result["learned"] == {
        "lessons": 2,
        "notes": 1,
    }
    assert (
        "mesafe sensörü" in next_brief(table.reviews(), "bahce")
        and next_brief(table.reviews(), "yok") is None
    )
    assert "Amaç: gezgin" in summarize(
        {
            "genome_id": "a",
            "mechanical": {"generated": {"purpose": "gezgin", "brief": ""}, "imports": []},
        }
    )


def test_a_lesson_that_does_not_cut_the_missing_things_is_dropped_and_one_that_does_is_proven(tmp_path):
    from neml_brain.learning.roundtable import RoundTable

    store = LearningStore(tmp_path / "learning")
    base = {"domain": "design", "kind": "roundtable", "call": {"name": "x", "arguments": {}}, "situation": "s", "status": "accepted", "ts": 1, "decided_at": 1}
    store.save_lessons({"a": {**base, "id": "a", "fp": "a", "baseline_missing": 3}, "b": {**base, "id": "b", "fp": "b", "baseline_missing": 3, "situation": "t"}})
    table = RoundTable(None, store, None, None)
    for missing_a in (1, 1, 1):
        table._measure(["a"], missing_a)  # noqa: SLF001
    for _ in range(3):
        table._measure(["b"], 4)  # noqa: SLF001
    lessons = store.lessons()
    assert lessons["a"]["proven"] is True and lessons["a"]["status"] == "accepted"
    assert lessons["b"]["status"] == "rejected" and "azaltmadı" in lessons["b"]["reason"]
    from neml_brain.learning.propose import shown

    assert [x["id"] for x in shown(store, "design")] == ["a"]


def test_identical_round_table_lessons_collapse_to_one(tmp_path):
    from neml_brain.learning.roundtable import RoundTable

    store = LearningStore(tmp_path / "learning")
    row = {"domain": "design", "kind": "roundtable", "call": {"name": "x", "arguments": {}}, "situation": "same", "status": "accepted", "ts": 1}
    store.save_lessons({k: {**row, "id": k, "fp": k} for k in "abc"})
    RoundTable(None, store, None, None)
    assert list(store.lessons()) == ["a"]
