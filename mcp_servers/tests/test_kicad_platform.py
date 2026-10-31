# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""KiCad adapter boundary tests without the KiCad binary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_servers.neml_mcp_kicad import emit, server


def test_kicad_rejects_output_outside_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEML_ARTIFACT_DIR", str(tmp_path))
    with pytest.raises(PermissionError):
        server._artifact(str(tmp_path.parent / "escape"))


def _fake_cli(monkeypatch: pytest.MonkeyPatch, report: dict, observed: list) -> None:  # type: ignore[type-arg]
    async def fake_run(argv: list[str], timeout_s: float) -> str:
        observed.append((argv, timeout_s))
        Path(argv[argv.index("-o") + 1]).write_text(json.dumps(report), encoding="utf-8")
        return ""

    monkeypatch.setattr(server, "run_cli", fake_run)


@pytest.mark.asyncio
async def test_kicad_drc_uses_cli_and_scoped_board(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEML_ARTIFACT_DIR", str(tmp_path))
    board = tmp_path / "board.kicad_pcb"
    board.write_text("(kicad_pcb)", encoding="utf-8")
    observed: list[tuple[list[str], float]] = []
    # unrouted nets are expected on a placed-but-untracked template board
    _fake_cli(monkeypatch, {"violations": [], "unconnected_items": [{"type": "x"}]}, observed)
    result = await server.run_drc(str(board))
    assert result["passed"] and result["unconnected"] == 1
    assert observed[0][0][1:3] == ["pcb", "drc"]


@pytest.mark.asyncio
async def test_kicad_erc_error_fails_but_warning_does_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEML_ARTIFACT_DIR", str(tmp_path))
    sch = tmp_path / "a.kicad_sch"
    sch.write_text("(kicad_sch)", encoding="utf-8")
    warn = {"severity": "warning", "type": "lib_symbol_issues"}
    _fake_cli(monkeypatch, {"sheets": [{"violations": [warn]}]}, [])
    assert (await server.run_erc(str(sch)))["warnings"] == 1
    err = {"severity": "error", "type": "pin_to_pin"}
    _fake_cli(monkeypatch, {"sheets": [{"violations": [warn, err]}]}, [])
    with pytest.raises(server.RuleViolation, match="pin_to_pin"):
        await server.run_erc(str(sch))


CIRCUIT = {
    "title": "demo",
    "parts": [
        {"ref": "U1", "value": "MCU", "kind": "IC", "package": "0805", "needs_decoupling": ["3V3"],
         "pins": [["1", "VCC", "power_in", "3V3"], ["2", "IO1", "bidirectional", "SIG"], ["3", "IO2", "bidirectional", "RST"], ["4", "GND", "power_in", "GND"]]},
        {"ref": "C1", "value": "100n", "kind": "C", "decouples": "U1", "pins": [["1", "1", "passive", "3V3"], ["2", "2", "passive", "GND"]]},
        {"ref": "R1", "value": "10k", "kind": "R", "pins": [["1", "1", "passive", "RST"], ["2", "2", "passive", "3V3"]]},
        {"ref": "J1", "value": "HDR", "kind": "CONN", "package": "THT", "pins": [["1", "1", "passive", "3V3"], ["2", "2", "passive", "SIG"], ["3", "3", "passive", "GND"]]},
    ],
}


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda c: c["parts"][1].update(ref="R1"), "unique reference"),  # duplicate ref
        (lambda c: c["parts"][0].update(kind="MAGIC"), "kind must be"),
        (lambda c: c["parts"][1]["pins"].append(["3", "3", "passive", "GND"]), "exactly two pins"),
        (lambda c: c["parts"][0]["pins"][0].__setitem__(3, "bad net!"), "bad pin"),
        (lambda c: c["parts"][0].update(package="0402"), "0603"),  # SPEC 13.1: nothing smaller
        (lambda c: c["parts"].pop(1), "decoupling"),  # SPEC 13.2: a device without its capacitor
        (lambda c: c.update(limits={"max_voltage_v": 60}), "outside the allowed class"),
        (lambda c: c.update(limits={"max_digital_mhz": 100}), "outside the allowed class"),
        (lambda c: c.update(parts=[]), "2.."),
    ],
)
def test_a_circuit_is_checked_as_data_with_the_spec_rules(mutate, message):
    import copy

    circuit = copy.deepcopy(CIRCUIT)
    mutate(circuit)
    with pytest.raises(server.CircuitError, match=message):
        server.check_circuit(circuit)


@pytest.mark.asyncio
async def test_a_circuit_becomes_a_schematic_a_routed_board_and_a_bom(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEML_ARTIFACT_DIR", str(tmp_path))
    made = await server.build_circuit(CIRCUIT, str(tmp_path / "out"), "demo")
    assert made["routing"]["unrouted"] == [] and made["routing"]["tracks"] > 0
    board = Path(made["board"]).read_text(encoding="utf-8")
    assert board.count("(segment") == made["routing"]["tracks"] and "(footprint" in board
    assert "U1" in Path(made["schematic"]).read_text(encoding="utf-8")
    assert "100n_0603" in Path(made["bom"]).read_text(encoding="utf-8")
    again = await server.build_circuit(CIRCUIT, str(tmp_path / "out2"), "demo")
    assert Path(again["board"]).read_text(encoding="utf-8") == board  # the same circuit gives the same bytes


@pytest.mark.asyncio
async def test_placement_hints_move_parts_and_a_board_too_small_grows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import copy

    monkeypatch.setenv("NEML_ARTIFACT_DIR", str(tmp_path))
    moved = copy.deepcopy(CIRCUIT)
    moved["placement"] = {"J1": [30, 12]}
    made = await server.build_circuit(moved, str(tmp_path / "a"), "demo")
    assert made["places"]["J1"] == [30.0, 12.0]
    moved["size"] = [20, 20]
    small = await server.build_circuit(moved, str(tmp_path / "b"), "demo")  # a board drawn too small grows to fit its parts
    assert small["size_mm"][0] > 20
    with pytest.raises(server.CircuitError, match="not a part"):
        await server.build_circuit({**CIRCUIT, "placement": {"X9": [1, 1]}}, str(tmp_path / "c"), "demo")


def test_parts_with_different_pin_names_get_their_own_symbols() -> None:
    import copy

    circuit = copy.deepcopy(CIRCUIT)
    circuit["parts"][2]["pins"] = [["1", "+", "passive", "3V3"], ["2", "-", "passive", "GND"]]  # another naming of the same kind of part
    parts = server.check_circuit(circuit)
    symbols = {p["ref"]: p["symbol"] for p in parts}
    assert symbols["C1"] != symbols["R1"] and symbols["R1"] != "R2"
    assert server.check_circuit(CIRCUIT)  # the plain circuit still passes the SPEC 13.2 audit


def test_every_pad_of_a_routed_net_has_a_track_ending_inside_its_copper() -> None:
    """The check KiCad's DRC makes (a pad with no track on it is 'unconnected'), done on the router's output."""
    from mcp_servers.neml_mcp_kicad import emit, route

    parts = server.check_circuit(CIRCUIT)
    places, w, h = emit.autoplace(parts)
    routing = route.autoroute(parts, places, (w, h))
    assert routing["unrouted"] == []
    ends = [(net, p) for net, _layer, a, b, _w in routing["tracks"] for p in (a, b)]
    for part in parts:
        cx, cy = places[part["ref"]]
        nets = {n: net for n, _name, _t, net in part["pins"]}
        for num, px, py, style, (pw, ph), _drill in emit._pads(part):  # noqa: SLF001
            net = nets[num]
            if sum(1 for p in parts for pin in p["pins"] if pin[3] == net) < 2:
                continue
            ax, ay = cx + px, cy + py
            inside = [
                (x, y) for n, (x, y) in ends if n == net
                and ((x - ax) ** 2 + (y - ay) ** 2 <= (pw / 2) ** 2 if style != "smd" else abs(x - ax) <= pw / 2 and abs(y - ay) <= ph / 2)
            ]
            assert inside, f"{part['ref']} pad {num} ({net}) has no track ending in its copper"


@pytest.mark.asyncio
async def test_the_second_reader_agrees_with_a_clean_board_and_sees_a_cut_track(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEML_ARTIFACT_DIR", str(tmp_path))
    made = await server.build_circuit(CIRCUIT, str(tmp_path / "x"), "demo")
    checked = await server.cross_check(CIRCUIT, made["board"])
    assert checked["issues"] == []
    geo = checked["geometry"]
    assert geo["pads"] and geo["tracks"] and set(geo["parts"]) == {p["ref"] for p in CIRCUIT["parts"]}  # the drawing a screen makes of the board
    board = Path(made["board"])
    lines = board.read_text(encoding="utf-8").splitlines()
    cut = next(i for i, ln in enumerate(lines) if ln.startswith("  (segment") and '"GND"' not in ln)
    board.write_text("\n".join(lines[:cut] + lines[cut + 1 :]), encoding="utf-8")
    assert (await server.cross_check(CIRCUIT, made["board"]))["issues"]


def test_overlapping_hints_are_pushed_apart() -> None:
    parts = emit_parts = server.check_circuit(CIRCUIT)
    places, _w, _h = emit.autoplace(parts, {"C1": (10, 10), "R1": (10.5, 10)})  # two parts on top of each other
    (x1, y1), (x2, y2) = places["C1"], places["R1"]
    hx1, hy1 = emit.extent(next(p for p in emit_parts if p["ref"] == "C1"))
    hx2, hy2 = emit.extent(next(p for p in emit_parts if p["ref"] == "R1"))
    assert abs(x2 - x1) >= hx1 + hx2 or abs(y2 - y1) >= hy1 + hy2
