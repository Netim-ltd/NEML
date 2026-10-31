# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The learning loop: notice -> propose -> owner accepts."""

from __future__ import annotations

import pytest

from neml_brain.learning.propose import hints, propose, valid_call
from neml_brain.learning.store import LearningStore
from neml_brain.learning.tick import tick


class FakeLlm:
    def __init__(self, out):
        self.out, self.calls = out, 0

    async def fill(self, prompt, schema, profile="x"):
        self.calls += 1
        return self.out


def test_events_are_deduplicated_by_shape_not_numbers(tmp_path):
    store = LearningStore(tmp_path)
    assert store.note("assembly", "collision", "shell_lower ile compute 4 mm iç içe giriyor")
    assert not store.note(
        "assembly", "collision", "shell_lower ile compute 7 mm iç içe giriyor"
    )  # same shape within the hour
    assert not store.note("nowhere", "x", "text")  # unknown area
    assert len(store.unanswered()) == 1


@pytest.mark.asyncio
async def test_a_lesson_is_proposed_checked_and_then_decided(tmp_path, monkeypatch):
    monkeypatch.setenv("NEML_LEARNING_AUTO", "false")
    store = LearningStore(tmp_path)
    store.note("sim", "tipped_over", "robot 4.0 kg ile flat dünyasında devrildi")
    llm = FakeLlm(
        {"cause": "çok ağır", "call": {"name": "lower_body_mass", "arguments": {"mass_kg": 3.0}}}
    )
    lesson = await propose(store, llm, store.unanswered()[0])
    assert lesson and lesson["status"] == "proposed" and not store.unanswered()
    bad = FakeLlm(
        {"cause": "x", "call": {"name": "lower_body_mass", "arguments": {"mass_kg": "çok"}}}
    )
    store.note("sim", "tipped_over", "başka bir durum")
    assert await propose(store, bad, store.unanswered()[0]) is None  # off-schema remedy is refused
    assert hints(store, "sim") == ""  # nothing is a lesson until the owner accepts it
    store.decide(lesson["id"], "accepted")
    assert "lower_body_mass" in hints(store, "sim")
    assert valid_call(
        "sim", {"name": "ask_owner", "arguments": {"question": "?"}}
    ) and not valid_call("sim", {"name": "rm_rf", "arguments": {}})


def _accept(store, domain, n):
    lessons = store.lessons()
    for i in range(n):
        lessons[f"{domain}{i}"] = {
            "id": f"{domain}{i}",
            "fp": f"{domain}{i}",
            "domain": domain,
            "situation": f"durum {i}",
            "call": {"name": "ask_owner", "arguments": {"question": "?"}},
            "status": "accepted",
            "ts": i,
        }
    store.save_lessons(lessons)


@pytest.mark.asyncio
async def test_a_remedy_the_model_gives_twice_is_accepted_by_the_lab_itself(tmp_path, monkeypatch):
    class TwoVoices:
        def __init__(self, first, second):
            self.answers = [first, second]

        async def fill(self, prompt, schema, profile="x"):
            return self.answers.pop(0)

    mass = {"cause": "ağır", "call": {"name": "lower_body_mass", "arguments": {"mass_kg": 3.0}}}
    other = {
        "cause": "ağır",
        "call": {"name": "retry_sim", "arguments": {"world": "flat", "duration_s": 8}},
    }
    store = LearningStore(tmp_path)
    store.note("sim", "tipped_over", "robot 4.0 kg ile flat dünyasında devrildi")
    store.note("sim", "run_failed", "koşu başarısız (maze)")
    agreeing = await propose(store, TwoVoices(mass, mass), store.unanswered()[0])
    split = await propose(store, TwoVoices(mass, other), store.unanswered()[0])
    assert agreeing["status"] == "accepted" and agreeing["auto"]
    assert (
        split["status"] == "proposed" and not split["auto"]
    )  # the voices differ: left to the owner
    monkeypatch.setenv("NEML_LEARNING_AUTO", "false")
    store.note("sim", "x", "başka bir şey oldu")
    assert (await propose(store, FakeLlm(mass), store.unanswered()[0]))["status"] == "proposed"


def test_radar_reads_rss_and_atom_entries():
    from neml_brain.learning.radar import entries

    rss = "<rss><channel><item><title><![CDATA[Yeni <b>bacak</b>]]></title><link>https://hackaday.com/a</link></item></channel></rss>"
    atom = '<feed><entry><title>Paper</title><link href="https://arxiv.org/abs/1"/></entry><entry><title>x</title><link href="http://insecure/"/></entry></feed>'
    assert entries(rss) == [("Yeni bacak", "https://hackaday.com/a")]
    assert entries(atom) == [("Paper", "https://arxiv.org/abs/1")]  # https only


@pytest.mark.asyncio
async def test_radar_learns_each_entry_once_and_survives_a_dead_feed(tmp_path):
    from neml_brain.learning.radar import Radar

    class Mcp:
        def __init__(self):
            self.fail = False

        async def call(self, server, tool, args, timeout=0):
            if self.fail:
                raise RuntimeError("down")
            return {
                "text": "<rss><item><title>A</title><link>https://hackaday.com/a</link></item></rss>"
            }

    class Researcher:
        def __init__(self):
            self.pages = []

        async def learn_pages(self, topic, urls):
            self.pages += urls
            return {"notes": [{"x": 1}]}

    mcp, res = Mcp(), Researcher()
    radar = Radar(mcp, res, tmp_path)
    first = await radar.tick()
    radar._state["cursor"] = 0
    again = await radar.tick()
    assert (
        first["new"] == 1
        and first["notes"] == 1
        and again["new"] == 0
        and res.pages == ["https://hackaday.com/a"]
    )
    mcp.fail = True
    assert (await radar.tick())["ok"] is False and radar.status()["log"][0]["title"] == "A"


@pytest.mark.asyncio
async def test_a_tick_proposes_one_by_day_and_more_at_night(tmp_path):
    store = LearningStore(tmp_path)
    for i in range(3):
        store.note("import", "k", f"{'abc'[i] * 5} deposu {'x' * i} mesh yok")
    llm = FakeLlm({"cause": "c", "call": {"name": "ask_owner", "arguments": {"question": "?"}}})
    assert await tick(store, llm, night=False) == {"proposed": 1}
    assert (await tick(store, llm, night=True))["proposed"] == 2
