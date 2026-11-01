# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The CAD benchmark: known parts, volumes worked out by hand."""

import pytest

from neml_brain.evolution.bench import CASES, CadBench, Evolver, score


def _built(case, scale=1.0):
    x, y, z = case["dims"]
    return {"bbox": [0, 0, 0, x, y, z], "volume_mm3": case["volume"] * scale}


def test_a_part_with_the_right_volume_and_box_passes_and_a_hollow_one_does_not():
    box = CASES[0]
    assert score(box, _built(box))["passed"]
    assert not score(box, _built(box, 0.5))["passed"]  # a hole nobody asked for
    assert all(c["volume"] > 0 and len(c["dims"]) == 3 for c in CASES)


@pytest.mark.asyncio
async def test_the_bench_runs_every_case_and_keeps_the_report(tmp_path):
    class Gen:
        async def _part(self, lk, out, progress, rules=None, **_):
            case = next(c for c in CASES if c["id"] == lk["name"])
            if case["id"] == "merdiven":
                raise RuntimeError("tarif reddedildi")
            return _built(case)

    bench = CadBench(Gen(), tmp_path / "w", tmp_path)
    bench.start()
    await bench._task  # noqa: SLF001
    report = bench.report()
    assert report["state"] == "done" and report["passed"] == len(CASES) - 1
    assert next(c for c in report["cases"] if c["id"] == "merdiven")["error"]


@pytest.mark.asyncio
async def test_a_rule_stays_only_when_more_cases_pass_with_it(tmp_path):
    class Gen:
        rules: list = []

        def busy(self):
            return False

        async def _part(self, lk, out, progress, rules=None, **_):
            case = next(c for c in CASES if c["id"] == lk["name"])
            good = "iyi kural" in (rules or [])
            return _built(case, 1.0 if good or case["id"] != "flans" else 0.5)

    class Llm:
        def __init__(self, rules):
            self.rules = iter(rules)

        async def fill(self, prompt, schema, profile="x", max_tokens=None, temperature=0.0):
            return {"action": "add", "index": 0, "rule": next(self.rules)}

    gen = Gen()
    evolver = Evolver(CadBench(gen, tmp_path / "w", tmp_path), gen, Llm(["işe yaramaz", "iyi kural"]), tmp_path)
    first = await evolver.step()
    assert first["history"][-1]["kept"] is False and first["history"][-1]["stage"] == 1 and gen.rules == []  # stopped after the cheap stage
    second = await evolver.step()
    assert second["history"][-1]["kept"] is True and gen.rules == ["iyi kural"] and second["best"] == len(CASES) and second["history"][-1]["stage"] == 2
    assert Evolver(CadBench(gen, tmp_path / "w", tmp_path), Gen(), Llm([]), tmp_path)._gen.rules == ["iyi kural"]  # noqa: SLF001 - survives a restart


def test_a_proposed_change_adds_replaces_or_removes_a_rule():
    from neml_brain.evolution.bench import apply

    assert apply(["a"], {"action": "add", "index": 0, "rule": "b"}) == ["a", "b"]
    assert apply(["a", "b"], {"action": "replace", "index": 1, "rule": "c"}) == ["a", "c"]
    assert apply(["a", "b"], {"action": "remove", "index": 0, "rule": ""}) == ["b"]
    assert apply(["a"], {"action": "remove", "index": 5, "rule": ""}) == ["a"]


def test_a_replace_with_nothing_to_replace_becomes_a_new_rule():
    from neml_brain.evolution.bench import apply

    assert apply([], {"action": "replace", "index": 0, "rule": "r"}) == ["r"]


@pytest.mark.asyncio
async def test_a_rule_that_was_already_tried_is_not_measured_again(tmp_path):
    runs = []

    class Gen:
        rules: list = []

        def busy(self):
            return False

        async def _part(self, lk, out, progress, rules=None, **_):
            runs.append(list(rules or []))
            return _built(next(c for c in CASES if c["id"] == lk["name"]), 0.5)

    class Llm:
        async def fill(self, prompt, schema, profile="x", max_tokens=None, temperature=0.0):
            return {"action": "add", "index": 0, "rule": "aynı kural"}

    gen = Gen()
    evolver = Evolver(CadBench(gen, tmp_path / "w", tmp_path), gen, Llm(), tmp_path)
    await evolver.step()
    before = len(runs)
    again = await evolver.step()
    assert len(runs) == before and again["history"][-1]["stage"] == 0


@pytest.mark.asyncio
async def test_a_repeated_rule_is_asked_again_hotter_and_a_new_one_is_taken(tmp_path):
    asked = []

    class Gen:
        rules: list = []

        def busy(self):
            return False

        async def _part(self, lk, out, progress, rules=None, **_):
            return _built(next(c for c in CASES if c["id"] == lk["name"]), 0.5)

    class Llm:
        async def fill(self, prompt, schema, profile="x", max_tokens=None, temperature=0.0):
            asked.append(temperature)
            return {"action": "add", "index": 0, "rule": "eski" if len(asked) < 3 else "yeni"}

    gen = Gen()
    evolver = Evolver(CadBench(gen, tmp_path / "w", tmp_path), gen, Llm(), tmp_path)
    evolver._save({"rules": [], "best": 0, "cases": [{"id": c["id"], "passed": False} for c in CASES], "history": [{"rule": "add: eski", "kept": False}], "archive": [{"rules": [], "passed": 0, "cases": [{"id": c["id"], "passed": False} for c in CASES]}]})  # noqa: SLF001
    done = await evolver.step()
    assert asked == [0.0, 0.8, 1.0] and done["history"][-1]["rule"] == "add: yeni"


@pytest.mark.asyncio
async def test_a_checked_recipe_is_kept_and_shown_for_a_similar_part_but_never_for_its_own_case(tmp_path):
    from neml_brain.evolution.skills import SkillLibrary

    lib = SkillLibrary(tmp_path)

    class Gen:
        skills = lib

        async def _part(self, lk, out, progress, rules=None, **_):
            case = next(c for c in CASES if c["id"] == lk["name"])
            built = _built(case, 1.0 if case["id"] == "flans" else 0.5)
            built["recipe"] = {"result": case["id"]}
            return built

    bench = CadBench(Gen(), tmp_path / "w", tmp_path)
    bench.start()
    await bench._task  # noqa: SLF001
    assert [s["key"] for s in lib.all() if s["source"] != "seed"] == ["flans"]  # only the case that passed
    assert "flans" in lib.examples("Çapı 80 mm yuvarlak flanş, ortasında delik")
    assert "flans" not in lib.examples("Çapı 80 mm yuvarlak flanş, ortasında delik", exclude="flans")  # seeds may be shown, its own answer never


def test_the_benchmark_has_more_than_nine_cases_with_unique_ids():
    assert len(CASES) >= 18 and len({c["id"] for c in CASES}) == len(CASES)


@pytest.mark.asyncio
async def test_a_researched_note_is_tried_as_a_rule_and_the_benchmark_judges_it(tmp_path):
    from neml_brain.evolution.knowledge import KnowledgeBase

    base = KnowledgeBase(tmp_path)
    base.add("konu", "https://x.org/a", [{"title": "t", "rule": "kaynaklı kural", "quote": "q", "area": "cad"}])
    note = base.all()[0]
    assert note["status"] == "unverified" and [n["id"] for n in base.untested("cad")] == [note["id"]]

    class Gen:
        rules: list = []

        def busy(self):
            return False

        async def _part(self, lk, out, progress, rules=None, **_):
            return _built(next(c for c in CASES if c["id"] == lk["name"]), 1.0 if "iyi" in " ".join(rules or []) or lk["name"] != "flans" else 0.5)

    class Llm:
        async def fill(self, prompt, schema, profile="x", max_tokens=None, temperature=0.0):
            assert note["id"] in prompt  # the claim is shown to the proposer with its id
            return {"action": "add", "index": 0, "rule": "iyi kural", "note": note["id"]}

    gen = Gen()
    evolver = Evolver(CadBench(gen, tmp_path / "w", tmp_path), gen, Llm(), tmp_path, notes=base)
    done = await evolver.step()
    assert done["history"][-1]["kept"] and base.all()[0]["status"] == "verified" and base.all()[0]["evidence"][0]["after"] > base.all()[0]["evidence"][0]["before"]
    assert base.relevant("kaynaklı kural")[0]["id"] == note["id"]


def test_a_note_the_benchmark_disproved_twice_is_rejected_and_no_longer_shown(tmp_path):
    from neml_brain.evolution.knowledge import KnowledgeBase

    base = KnowledgeBase(tmp_path)
    base.add("konu", "https://x.org/a", [{"title": "t", "rule": "boş kural cümlesi", "quote": "q", "area": "cad"}])
    nid = base.all()[0]["id"]
    assert base.judge(nid, False, {}) == "unverified" and base.judge(nid, False, {}) == "rejected"
    assert base.relevant("boş kural cümlesi") == [] and base.untested("cad") == []
