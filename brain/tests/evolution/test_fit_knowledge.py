# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The web-learned design notes and safe model names."""

from __future__ import annotations

import asyncio

from neml_brain.evolution.knowledge import KnowledgeBase, Researcher


def test_notes_are_kept_deduplicated_found_by_words_and_forgotten(tmp_path):
    base = KnowledgeBase(tmp_path)
    base.add(
        "servo mount",
        "https://en.wikipedia.org/x",
        [{"title": "Servo payı", "rule": "Servo ile gövde arasında 2 mm pay bırak."}],
    )
    again = base.add(
        "servo mount",
        "https://en.wikipedia.org/x",
        [{"title": "t", "rule": "Servo ile gövde arasında 2 mm pay bırak."}],
    )
    assert again == [] and len(base.all()) == 1
    assert base.relevant("servo payı kaç mm olmalı")[0]["status"] == "unverified"
    assert base.relevant("tamamen alakasız kelimeler") == []
    assert base.forget(base.all()[0]["id"]) and base.all() == []


class FakeMcp:
    async def call(self, server, tool, args, timeout=None):
        if tool == "allowlist":
            return ["en.wikipedia.org"]
        if "dead" in args["url"]:
            raise RuntimeError("404")
        return {"text": "Üst ve alt bacak aynı uzunlukta yapılır.", "url": args["url"]}


class FakeLlm:
    async def fill(self, prompt, schema, profile=None):
        if "urls" in schema["properties"]:
            return {"urls": ["https://en.wikipedia.org/wiki/A", "https://en.wikipedia.org/dead"]}
        return {
            "notes": [
                {
                    "title": "Oran",
                    "rule": "Üst ve alt bacak eşit uzunlukta olmalı.",
                    "quote": "Üst ve alt bacak aynı uzunlukta yapılır.",
                },
                {
                    "title": "Uydurma",
                    "rule": "Kuyruk %25 olmalı.",
                    "quote": "Kuyruk yüzde yirmi beş olmalıdır diye bir cümle.",
                },
            ]
        }


def test_learning_reads_pages_skips_dead_links_and_stores_unverified_notes(tmp_path):
    base = KnowledgeBase(tmp_path)
    got = asyncio.run(Researcher(FakeMcp(), FakeLlm(), base).learn("quadruped leg proportions"))
    assert got["pages"] == ["https://en.wikipedia.org/wiki/A"] and len(got["failed"]) == 1
    assert [n["status"] for n in base.all()] == [
        "unverified"
    ]  # the invented note had no quote on the page


def test_new_model_names_are_safe_identifiers():
    from neml_brain.evolution.generative import model_name as slug

    assert slug("Bahçe Robotu!") == "bahce_robotu" and slug("42 legs") == "model_42_legs"
    assert slug("x" * 60) == "x" * 24
