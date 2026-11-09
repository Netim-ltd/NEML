# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
from copy import deepcopy

from neml_brain.learning.questions import Questions
from tests.evolution.test_generative import PLAN


def test_a_question_is_asked_once_and_the_answer_reaches_the_prompt(tmp_path):
    q = Questions(tmp_path)
    assert q.ask("Bütçe ne?") and not q.ask("Bütçe ne?")
    assert q.rules() == ""
    assert q.answer(q.all()[0]["id"], "en fazla 2000 TL")
    assert "en fazla 2000 TL" in q.rules()
    assert not q.answer("yok", "x")


def test_only_the_open_questions_are_capped(tmp_path):
    q = Questions(tmp_path)
    for i in range(8):
        q.ask(f"soru {i}")
    assert sum(1 for r in q.all() if r["answer"] is None) == 5


def test_a_kept_plan_comes_back_for_a_similar_request(tmp_path):
    q = Questions(tmp_path)
    plan = deepcopy(PLAN)
    q.keep("bahçe için tekerlekli gezgin robot", plan)
    assert plan["links"][0]["name"] in q.example("küçük tekerlekli gezgin istiyorum")
    assert q.example("tamamen alakasız kol manipülatör") == ""
