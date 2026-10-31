# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""KiCad circuit builder and DRC/ERC MCP server; KiCad runs in a separate process.

There are no board templates: an agent describes a circuit as data (parts, pins, nets, placement hints),
the server validates it, draws the schematic, places and routes the board and writes the BOM; KiCad's own
ERC/DRC then judge the result.
"""

from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path
from typing import Any

from mcp_servers._common import make_app, run_cli

PORT = 9105
VERSION = "1.0.0"


def _artifact(path: str, *, suffix: str | None = None) -> Path:
    root = Path(os.environ["NEML_ARTIFACT_DIR"]).resolve()
    target = Path(path).resolve()
    if target != root and root not in target.parents:
        raise PermissionError("KiCad artifact path is outside the configured root")
    if suffix and target.suffix != suffix:
        raise ValueError(f"expected {suffix} artifact")
    return target


class CircuitError(ValueError):
    """The circuit recipe is not a plain, in-scope circuit (the message tells the agent what to fix)."""


KINDS = ("R", "C", "L", "D", "LED", "IC", "CONN", "MOD", "SW", "Q", "F")
ETYPES = ("input", "output", "bidirectional", "passive", "power_in", "power_out", "unspecified")
REF = re.compile(r"^[A-Z]{1,3}[0-9]{1,3}$")
NET = re.compile(r"^[A-Za-z0-9_+\-./]{1,24}$")
MAX_PARTS = 60
MAX_PINS = 40
# SPEC 13.1: two layers, <=10 A, <=48 V, digital below 10 MHz. A circuit that declares more is refused.
SCOPE = {"max_current_a": 10.0, "max_voltage_v": 48.0, "max_digital_mhz": 10.0}


def _number(value: Any, low: float, high: float, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not low <= value <= high:
        raise CircuitError(f"{what} must be a number in [{low}, {high}]")
    return float(value)


def _symbol_for(kind: str, pins: list[tuple[str, str, str, str]]) -> str:
    """One symbol per distinct pinout, so two parts with different pin names never share a drawing."""
    import hashlib

    signature = json.dumps([(n, name, etype) for n, name, etype, _net in pins])
    return f"{kind}{len(pins)}_{hashlib.sha1(signature.encode()).hexdigest()[:6]}"  # noqa: S324 - a name, not a secret


def check_circuit(circuit: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate a circuit recipe as data and return its parts as emit.part() dicts."""
    from mcp_servers.neml_mcp_kicad import emit

    if not isinstance(circuit, dict) or not isinstance(circuit.get("title"), str) or not 1 <= len(circuit["title"]) <= 60:
        raise CircuitError("title is required (1..60 characters)")
    raw = circuit.get("parts")
    if not isinstance(raw, list) or not 2 <= len(raw) <= MAX_PARTS:
        raise CircuitError(f"a circuit has 2..{MAX_PARTS} parts")
    limits = circuit.get("limits") or {}
    for key, ceiling in SCOPE.items():
        if key in limits:
            value = _number(limits[key], 0, 1e6, key)
            if value > ceiling or (key == "max_digital_mhz" and value >= ceiling):
                raise CircuitError(f"SPEC 13.1: {key} {value:g} is outside the allowed class (limit {ceiling:g})")
    parts = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise CircuitError("every part is an object")
        ref = item.get("ref")
        if not isinstance(ref, str) or not REF.match(ref) or ref in seen:
            raise CircuitError(f"part ref {ref!r}: a unique reference like R1, U2, J3")
        seen.add(ref)
        kind = item.get("kind")
        if kind not in KINDS:
            raise CircuitError(f"{ref}: kind must be one of {', '.join(KINDS)}")
        pins = item.get("pins")
        if not isinstance(pins, list) or not 1 <= len(pins) <= MAX_PINS:
            raise CircuitError(f"{ref}: 1..{MAX_PINS} pins")
        clean = []
        numbers: set[str] = set()
        for pin in pins:
            if not (isinstance(pin, list) and len(pin) == 4 and all(isinstance(v, str) for v in pin)):
                raise CircuitError(f"{ref}: a pin is [number, name, electrical type, net]")
            num, name, etype, net = pin
            if num in numbers:
                raise CircuitError(f"{ref}: pin number {num!r} is used twice; every pin has its own number (1, 2, 3, ...) and several pins may share a net name such as GND")
            if not 1 <= len(num) <= 4 or not 1 <= len(name) <= 20 or etype not in ETYPES or not NET.match(net):
                raise CircuitError(f"{ref}: bad pin {pin} (unique number, name, type in {', '.join(ETYPES)}, net like 3V3 or SIG_1)")
            numbers.add(num)
            clean.append((num, name, etype, net))
        package = item.get("package", "0603")
        if kind not in ("IC", "CONN", "MOD") and package != "THT" and len(clean) != 2:
            raise CircuitError(f"{ref}: a {kind} in an SMD package has exactly two pins")
        try:
            parts.append(
                emit.part(
                    ref,
                    str(item.get("value", ""))[:30],
                    kind,
                    clean,
                    symbol=str(item.get("symbol") or _symbol_for(kind, clean)),
                    package=package,
                    part_number=str(item.get("part_number", ""))[:40],
                    supplier=str(item.get("supplier", "LCSC"))[:20],
                    unit_cost_try=_number(item.get("unit_cost_try", 0.0), 0, 1e6, f"{ref} unit_cost_try"),
                    lead_time_days=int(_number(item.get("lead_time_days", 7), 0, 365, f"{ref} lead_time_days")),
                    decouples=item.get("decouples"),
                    needs_decoupling=tuple(str(n) for n in item.get("needs_decoupling", ())),
                    needs_pull={str(k): str(v) for k, v in dict(item.get("needs_pull") or {}).items()},
                )
            )
        except emit.DesignError as exc:
            raise CircuitError(str(exc)) from exc
    try:
        emit.audit(parts)
    except emit.DesignError as exc:
        raise CircuitError(str(exc)) from exc
    return parts


async def build_circuit(circuit: dict[str, Any], out_dir: str, name: str) -> dict[str, Any]:
    """Draw a circuit recipe: schematic, placed and routed board, BOM. Nothing the caller sends is executed."""
    from mcp_servers.neml_mcp_kicad import emit, route

    if not re.fullmatch(r"[a-z][a-z0-9_]{1,40}", name):
        raise ValueError("name must be lowercase letters, digits and underscores")
    parts = check_circuit(circuit)
    target = _artifact(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    placement = {}
    for ref, xy in dict(circuit.get("placement") or {}).items():
        if ref not in {p["ref"] for p in parts} or not (isinstance(xy, list) and len(xy) == 2):
            raise CircuitError(f"placement: {ref!r} is not a part or its position is not [x, y]")
        placement[ref] = (_number(xy[0], 0, 400, "x"), _number(xy[1], 0, 400, "y"))
    track = _number(circuit.get("track_mm", 0.25), 0.15, 1.0, "track_mm")
    places, width, height = emit.autoplace(parts, placement)
    size = circuit.get("size")
    if size:
        width = max(width, _number(size[0], 10, 400, "width"))  # a board the agent drew too small grows to fit its parts
        height = max(height, _number(size[1], 10, 400, "height"))
    for p in parts:  # a part pushed over the board edge is a mistake the agent can fix
        if p["kind"] != "FLG":
            hx, hy = emit.extent(p)
            x, y = places[p["ref"]]
            if x - hx < 0 or y - hy < 0 or x + hx > width or y + hy > height:
                raise CircuitError(f"{p['ref']} sticks out of the {width:.0f}x{height:.0f} mm board at ({x:.0f}, {y:.0f})")
    routing = route.autoroute(parts, places, (width, height), track)
    schematic = target / f"{name}.kicad_sch"
    board = target / f"{name}.kicad_pcb"
    bom = target / f"{name}.csv"
    schematic.write_text(emit.schematic_text(circuit["title"], parts), encoding="utf-8")
    board.write_text(
        emit.pcb_text(circuit["title"], parts, places, (width, height), routing["tracks"], routing["vias"]),
        encoding="utf-8",
    )
    rows = emit.bom_rows(parts)
    with bom.open("w", encoding="utf-8", newline="") as handle:
        columns = sorted({str(key) for row in rows for key in row})
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return {
        "schematic": str(schematic),
        "board": str(board),
        "bom": str(bom),
        "size_mm": [round(width, 1), round(height, 1)],
        "places": {ref: [round(x, 2), round(y, 2)] for ref, (x, y) in places.items()},
        "routing": {k: routing[k] for k in ("routed", "unrouted", "length_mm")} | {"vias": len(routing["vias"]), "tracks": len(routing["tracks"])},
    }


class RuleViolation(RuntimeError):
    """KiCad reported error-level violations; the artifact must not be used as is."""


async def _check(kind: str, target: Path, report: Path, timeout_s: float) -> dict[str, Any]:
    """Run `kicad-cli <pcb drc|sch erc>` and rule on its JSON report.

    The exit code is not used: kicad-cli exits 0 with violations unless asked, and
    with --exit-code-violations it also fails on warnings and on the unrouted nets a
    placed-but-untracked template board legitimately has (SPEC 13.2). The JSON keeps
    those apart, so the verdict is "no error-level violation".
    """
    sub = ["pcb", "drc"] if kind == "drc" else ["sch", "erc"]
    await run_cli(
        [
            os.getenv("KICAD_CLI_BIN", "kicad-cli"),
            *sub,
            "--format",
            "json",
            "-o",
            str(report),
            str(target),
        ],
        timeout_s,
    )
    if not report.is_file():
        raise RuntimeError(f"kicad-cli wrote no {kind.upper()} report")
    data = json.loads(report.read_text(encoding="utf-8"))
    found = list(data.get("violations", []))
    for sheet in data.get("sheets", []):
        found.extend(sheet.get("violations", []))
    errors = [v for v in found if v.get("severity") == "error"]
    if errors:
        kinds = sorted({str(v.get("type")) for v in errors})
        what = sorted({str(v.get("description", ""))[:90] for v in errors})[:4]
        raise RuleViolation(f"{len(errors)} {kind.upper()} error(s): {', '.join(kinds)} ({'; '.join(what)})")
    return {
        "report": str(report),
        "passed": True,
        "warnings": len(found) - len(errors),
        "unconnected": len(data.get("unconnected_items", [])),
    }


async def run_drc(board_path: str, timeout_s: float = 180.0) -> dict[str, Any]:
    """Run KiCad PCB design rules and fail on any error-level violation."""
    board = _artifact(board_path, suffix=".kicad_pcb")
    if not board.is_file():
        raise FileNotFoundError("KiCad board missing")
    return {"board": str(board)} | await _check(
        "drc", board, board.with_suffix(".drc.json"), timeout_s
    )


async def run_erc(schematic_path: str, timeout_s: float = 180.0) -> dict[str, Any]:
    """Run KiCad electrical rules and fail on any error-level violation."""
    schematic = _artifact(schematic_path, suffix=".kicad_sch")
    if not schematic.is_file():
        raise FileNotFoundError("KiCad schematic missing")
    return {"schematic": str(schematic)} | await _check(
        "erc", schematic, schematic.with_suffix(".erc.json"), timeout_s
    )


async def cross_check(circuit: dict[str, Any], board_path: str) -> dict[str, Any]:
    """Read the drawn board with our own reader (not KiCad) and compare it with the circuit recipe."""
    from mcp_servers.neml_mcp_kicad import crosscheck

    parts = check_circuit(circuit)
    board = _artifact(board_path, suffix=".kicad_pcb")
    if not board.is_file():
        raise FileNotFoundError("KiCad board missing")
    return crosscheck.cross_check({"parts": parts}, board.read_text(encoding="utf-8"))


async def export_bom(circuit: dict[str, Any], out_dir: str, name: str) -> dict[str, str]:
    """The BOM of a circuit recipe alone (no board is drawn)."""
    from mcp_servers.neml_mcp_kicad import emit

    parts = check_circuit(circuit)
    target = _artifact(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    bom = target / f"{name}.csv"
    rows = emit.bom_rows(parts)
    with bom.open("w", encoding="utf-8", newline="") as handle:
        columns = sorted({str(key) for row in rows for key in row})
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return {"bom": str(bom)}


async def render(
    schematic_path: str, board_path: str, out_dir: str, timeout_s: float = 120.0
) -> dict[str, str]:
    """SVG pictures of the schematic and of the board (copper, silkscreen and outline).

    Pictures only: nothing here checks the design (run_erc and run_drc do), and the SVGs are
    written under the artifact root like every other KiCad output.
    """
    schematic = _artifact(schematic_path, suffix=".kicad_sch")
    board = _artifact(board_path, suffix=".kicad_pcb")
    target = _artifact(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    cli = os.getenv("KICAD_CLI_BIN", "kicad-cli")
    await run_cli(
        [cli, "sch", "export", "svg", "--no-background-color", "-o", str(target), str(schematic)],
        timeout_s,
    )
    pcb_svg = target / f"{board.stem}-pcb.svg"
    await run_cli(
        [
            cli,
            "pcb",
            "export",
            "svg",
            "--layers",
            "F.Cu,B.Cu,F.Silkscreen,Edge.Cuts",
            "--page-size-mode",
            "2",
            "--exclude-drawing-sheet",
            "-o",
            str(pcb_svg),
            str(board),
        ],
        timeout_s,
    )
    sheets = sorted(p for p in target.glob("*.svg") if p != pcb_svg)
    if not sheets or not pcb_svg.is_file():
        raise RuntimeError("kicad-cli wrote no SVG")
    return {"schematic_svg": str(sheets[0]), "board_svg": str(pcb_svg)}


async def _count(kind: str, target: Path, timeout_s: float) -> dict[str, Any]:
    """ERC or DRC counts of a foreign design: errors are data here, not a failure."""
    report = target.with_suffix(f".{kind}.json")
    sub = ["pcb", "drc"] if kind == "drc" else ["sch", "erc"]
    try:
        await run_cli(
            [
                os.getenv("KICAD_CLI_BIN", "kicad-cli"),
                *sub,
                "--format",
                "json",
                "-o",
                str(report),
                str(target),
            ],
            timeout_s,
        )
        data = json.loads(report.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - a design KiCad cannot even load is reported, not raised
        return {"ran": False, "reason": str(exc)[:200]}
    found = list(data.get("violations", []))
    for sheet in data.get("sheets", []):
        found.extend(sheet.get("violations", []))
    errors = [v for v in found if v.get("severity") == "error"]
    return {
        "ran": True,
        "errors": len(errors),
        "warnings": len(found) - len(errors),
        "kinds": sorted({str(v.get("type")) for v in errors})[:8],
    }


async def inspect_design(
    schematic_path: str = "", board_path: str = "", out_dir: str = "", timeout_s: float = 180.0
) -> dict[str, Any]:
    """Pictures and rule counts of a design imported from outside (either file may be missing)."""
    cli = os.getenv("KICAD_CLI_BIN", "kicad-cli")
    out: dict[str, Any] = {}
    target = _artifact(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    if schematic_path:
        schematic = _artifact(schematic_path, suffix=".kicad_sch")
        out["erc"] = await _count("erc", schematic, timeout_s)
        try:
            await run_cli(
                [
                    cli,
                    "sch",
                    "export",
                    "svg",
                    "--no-background-color",
                    "-o",
                    str(target),
                    str(schematic),
                ],
                timeout_s,
            )
            sheets = sorted(p for p in target.glob("*.svg") if not p.name.endswith("-pcb.svg"))
            if sheets:
                out["schematic_svg"] = str(sheets[0])
        except Exception as exc:  # noqa: BLE001
            out["schematic_error"] = str(exc)[:200]
    if board_path:
        board = _artifact(board_path, suffix=".kicad_pcb")
        out["drc"] = await _count("drc", board, timeout_s)
        pcb_svg = target / f"{board.stem}-pcb.svg"
        try:
            await run_cli(
                [
                    cli,
                    "pcb",
                    "export",
                    "svg",
                    "--layers",
                    "F.Cu,B.Cu,F.Silkscreen,Edge.Cuts",
                    "--page-size-mode",
                    "2",
                    "--exclude-drawing-sheet",
                    "-o",
                    str(pcb_svg),
                    str(board),
                ],
                timeout_s,
            )
            if pcb_svg.is_file():
                out["board_svg"] = str(pcb_svg)
        except Exception as exc:  # noqa: BLE001
            out["board_error"] = str(exc)[:200]
    return out


app = make_app(
    "neml-mcp-kicad",
    VERSION,
    {
        "build_circuit": build_circuit,
        "run_drc": run_drc,
        "run_erc": run_erc,
        "cross_check": cross_check,
        "export_bom": export_bom,
        "render": render,
        "inspect_design": inspect_design,
    },
)

if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT)
