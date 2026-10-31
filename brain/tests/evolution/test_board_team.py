# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The board team: architect, BOM picker, Turkish sourcing, routing checker and reviewer, with fakes."""

from __future__ import annotations

import copy

import pytest

from neml_brain.evolution.board_team import BoardTeam, bom_lines
from neml_brain.learning.store import LearningStore

CIRCUIT = {
    "title": "sensör kartı",
    "parts": [
        {
            "ref": "U1",
            "value": "BNO085",
            "kind": "IC",
            "package": "0805",
            "needs_decoupling": ["3V3"],
            "pins": [
                ["1", "VCC", "power_in", "3V3"],
                ["2", "SDA", "bidirectional", "SDA"],
                ["3", "GND", "power_in", "GND"],
            ],
        },
        {
            "ref": "C1",
            "value": "100n",
            "kind": "C",
            "package": "0603",
            "decouples": "U1",
            "pins": [["1", "1", "passive", "3V3"], ["2", "2", "passive", "GND"]],
        },
        {
            "ref": "C2",
            "value": "100n",
            "kind": "C",
            "package": "0603",
            "pins": [["1", "1", "passive", "3V3"], ["2", "2", "passive", "GND"]],
        },
    ],
}


class Llm:
    """Answers each agent by what it is asked; the sensor is out of stock at first and the router needs one fix."""

    def __init__(self):
        self.calls = []

    async def fill(self, prompt, schema, profile="x", max_tokens=None):
        self.calls.append(prompt[:24])
        if prompt.startswith("Bir robot için elektronik kart tasarla"):
            return {
                "board_name": "imu_karti",
                "purpose": "IMU kartı",
                "circuit": copy.deepcopy(CIRCUIT),
            }
        if prompt.startswith("Bu kartın malzeme listesini seç"):
            alt = "stokta yok" in prompt
            return {
                "lines": [
                    {
                        "ref": "U1",
                        "part_number": "BNO055" if alt else "BNO085",
                        "supplier": "Robotistan",
                    },
                    {"ref": "C1", "part_number": "100n_0603", "supplier": "genel"},
                    {"ref": "C2", "part_number": "100n_0603", "supplier": "genel"},
                ]
            }
        if "mağaza arama sayfasında" in prompt:
            if "BNO085" in prompt:
                return {
                    "found": True,
                    "stock": "yok",
                    "price_try": 950,
                    "url": "https://www.robotistan.com/bno085",
                    "quote": "BNO085 IMU modülü 950,00 TL tükendi",
                }
            return {
                "found": True,
                "stock": "stokta",
                "price_try": 640,
                "url": "https://www.robotistan.com/bno055",
                "quote": "BNO055 IMU modülü 640,00 TL stokta",
            }
        if "yönlendirme (routing) ajanısın" in prompt:
            return {
                "diagnosis": "SDA çizilemedi: U1 yaklaştırıldı",
                "moves": [{"ref": "U1", "x": 12, "y": 10}],
                "track_mm": 0.2,
                "width_mm": 40,
                "height_mm": 30,
            }
        return {"verdict": "riskli", "risks": ["pull-up yok"], "verify_first": "I2C hattı"}


class Mcp:
    def __init__(self, tmp):
        self.tmp, self.builds, self.drcs = tmp, 0, 0

    async def call(self, server, tool, args, timeout=0):
        if tool == "build_circuit":
            self.builds += 1
            out = self.tmp / f"b{self.builds}"
            out.mkdir(parents=True, exist_ok=True)
            for ext in ("kicad_sch", "kicad_pcb", "csv"):
                (out / f"{args['name']}.{ext}").write_text(
                    "x" if ext != "csv" else "part_number,qty\n100n_0603,2\nBNO055,1\n",
                    encoding="utf-8",
                )
            unrouted = ["SDA"] if self.builds == 1 else []
            routed = ["3V3", "GND"] if unrouted else ["3V3", "GND", "SDA"]
            return {
                "schematic": str(out / f"{args['name']}.kicad_sch"),
                "board": str(out / f"{args['name']}.kicad_pcb"),
                "bom": str(out / f"{args['name']}.csv"),
                "size_mm": [30.0, 20.0],
                "places": {"U1": [8.0, 8.0], "C1": [20.0, 8.0], "C2": [24.0, 12.0]},
                "routing": {
                    "routed": routed,
                    "unrouted": unrouted,
                    "length_mm": 40.0,
                    "vias": 0,
                    "tracks": 9,
                },
            }
        if tool == "run_drc":
            self.drcs += 1
            return {"passed": True, "warnings": 0, "unconnected": 1 if self.drcs == 1 else 0}
        if tool == "run_erc":
            return {"passed": True, "warnings": 2}
        if tool == "render":
            for name in ("s.svg", "b.svg"):
                (self.tmp / name).write_text("<svg/>", encoding="utf-8")
            return {"schematic_svg": str(self.tmp / "s.svg"), "board_svg": str(self.tmp / "b.svg")}
        if tool == "fetch":
            return {
                "text": "BNO085 IMU modülü 950,00 TL tükendi"
                if "BNO085" in args["url"]
                else "BNO055 IMU modülü 640,00 TL stokta"
            }
        raise AssertionError(tool)


class Uploader:
    async def upload(self, path, kind, name=None):
        return f"/api/v1/media/{kind}"


def test_bom_lines_group_identical_parts():
    lines = {line["part_number"]: line for line in bom_lines(CIRCUIT["parts"])}
    assert lines["100n_0603"]["qty"] == 2 and lines["100n_0603"]["refs"] == ["C1", "C2"]


@pytest.mark.asyncio
async def test_the_team_replaces_a_part_nobody_sells_in_turkey_and_fixes_the_routing(tmp_path):
    mcp = Mcp(tmp_path)
    store = LearningStore(tmp_path / "learning")
    team = BoardTeam(mcp, Uploader(), Llm(), store, tmp_path / "boards")
    talk = []
    out = await team.design("küçük bir IMU kartı", lambda agent, text: talk.append((agent, text)))
    agents = [a for a, _ in talk]
    assert agents[0] == "mimar" and {"malzeme", "tedarik", "yönlendirme", "eleştirmen"} <= set(
        agents
    )
    assert any("bulunamayan" in t for _, t in talk)  # the sourcing agent reported the missing part
    assert (
        out["circuit"]["parts"][0]["part_number"] == "BNO055"
    )  # and the picker replaced it with something buyable
    bom = {r["part_number"]: r for r in out["bom"]}
    assert bom["BNO055"]["tr"]["status"] == "bulundu" and bom["BNO055"]["tr"]["price_try"] == 640
    assert bom["100n_0603"]["tr"]["status"] == "genel"  # standard passives are not searched
    assert (
        out["clean"] and mcp.builds == 3
    )  # the first build left SDA unrouted, the router agent moved a part and it was clean
    assert out["circuit"]["placement"]["U1"] == [12, 10] and out["circuit"]["track_mm"] == 0.2
    assert (
        out["review"]["verdict"] == "riskli"
        and out["tr_total_try"] == 640.0
        and out["urls"]["board_svg"].endswith("svg")
    )


@pytest.mark.asyncio
async def test_a_price_without_a_quote_from_the_page_is_not_believed(tmp_path):
    class Liar(Llm):
        async def fill(self, prompt, schema, profile="x", max_tokens=None):
            if "mağaza arama sayfasında" in prompt:
                return {
                    "found": True,
                    "stock": "stokta",
                    "price_try": 1.0,
                    "url": "https://x",
                    "quote": "ürün çok ucuz ve hemen teslim edilir",
                }
            return await super().fill(prompt, schema, profile, max_tokens)

    team = BoardTeam(
        Mcp(tmp_path), Uploader(), Liar(), LearningStore(tmp_path / "learning"), tmp_path / "boards"
    )
    line = {
        "part_number": "BNO055",
        "kind": "MOD",
        "package": "THT",
        "value": "BNO055",
        "refs": ["U1"],
    }
    got = await team._find(line)  # noqa: SLF001
    assert got["status"] == "doğrulanamadı" and "arama" in got["url"]


@pytest.mark.asyncio
async def test_a_failed_design_is_a_learning_event_and_jobs_are_kept(tmp_path):
    class Broken(Llm):
        async def fill(self, prompt, schema, profile="x", max_tokens=None):
            raise RuntimeError("model meşgul")

    store = LearningStore(tmp_path / "learning")
    team = BoardTeam(Mcp(tmp_path), Uploader(), Broken(), store, tmp_path / "boards")
    job = team.start("bir kart", "owner")
    for task in list(team._running):  # noqa: SLF001
        await task
    saved = team.jobs()[0]
    assert saved["id"] == job["id"] and saved["state"] == "failed" and "meşgul" in saved["error"]
    assert any(e["domain"] == "electronics" for e in store.events())


@pytest.mark.asyncio
async def test_a_restarted_board_goes_on_from_its_checkpoint(tmp_path):
    import time

    llm = Llm()
    team = BoardTeam(Mcp(tmp_path), Uploader(), llm, LearningStore(tmp_path / "learning"), tmp_path / "boards")
    job = {
        "id": "abc",
        "brief": "küçük bir IMU kartı",
        "actor": "owner",
        "state": "running",
        "talk": [],
        "at": time.time(),
        "ckpt": {
            "circuit": copy.deepcopy(CIRCUIT),
            "name": "imu_karti",
            "purpose": "IMU kartı",
            "sourcing": {},
            "erc_round": 0,
            "picked": False,
        },
    }
    team._save(job)  # noqa: SLF001
    assert team.resume() == 1
    for task in list(team._running):  # noqa: SLF001
        await task
    saved = team.jobs()[0]
    assert saved["state"] == "done" and saved["resumes"] == 1 and "ckpt" not in saved
    assert not any(c.startswith("Bir robot için elektronik") for c in llm.calls)  # the architect is not asked again
    assert any(t["agent"] == "sistem" for t in saved["talk"])
