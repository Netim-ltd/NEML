# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The shipped seed recipes and the skill library."""

from neml_brain.evolution.skills import SkillLibrary


def test_the_shipped_seeds_are_shown_for_a_similar_part_and_a_learned_recipe_replaces_one(tmp_path):
    lib = SkillLibrary(tmp_path)
    assert len(lib.all()) >= 10 and all(s["recipe"]["result"] for s in lib.all())
    hit = lib.similar("rulman yatağı 22 mm rulman yuvası ve dört vida deliği olan blok")
    assert hit and hit[0]["key"] == "rulman_yatagi"
    lib.add("rulman_yatagi", "benim", {"solids": [], "result": "x"}, "bench")
    assert [s for s in lib.all() if s["key"] == "rulman_yatagi"][0]["source"] == "bench"
    assert not (tmp_path / "skills.json").read_text(encoding="utf-8").count("kasnak_bosu")  # seeds are never copied into the learned file
