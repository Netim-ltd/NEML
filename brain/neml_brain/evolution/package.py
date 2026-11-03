# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The build package of a designed robot: what to buy, how it is wired, how to put it together.

Everything is derived from the stored plan (links, bought catalog parts, joints), nothing is asked of a model, so a package costs no
LLM time and is the same every time. `package(plan)` returns {parts, wiring, steps, totals}.

# ponytail: wiring is by part kind (battery -> switch -> regulator -> board -> drivers -> motors/servos, sensors on the board), not
pin by pin; prices stay empty (the catalog says why) and a part carries a shop search phrase instead of an invented link."""

from __future__ import annotations

from typing import Any

from neml_brain.evolution.catalog import CATALOG
from neml_brain.evolution.mounts import MOUNTED

ELECTRIC = {"battery", "switch", "regulator", "board", "driver", "dc_motor", "servo", "sensor"}


def _bought(plan: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
    return [(lk, CATALOG.get(str(lk.get("part", "")))) for lk in plan["links"] if lk.get("source") == "bought"]


def parts_list(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Bill of materials: bought parts counted by catalog id, then the printed ones."""
    rows: dict[str, dict[str, Any]] = {}
    for lk, part in _bought(plan):
        key = part["id"] if part else f"diger:{lk['name']}"
        row = rows.setdefault(
            key,
            {"id": key, "name": part["name"] if part else str(lk["name"]), "kind": part["kind"] if part else "diger", "qty": 0,
             "unit_mass_g": float(lk.get("mass_g", 0)), "price": None, "search": part["name"] if part else str(lk.get("role", lk["name"])),
             "verified": bool(part and part["verified"])},
        )
        row["qty"] += 1
    printed = [
        {"id": f"baski:{lk['name']}", "name": str(lk["name"]), "kind": "3d_baski", "qty": 1, "unit_mass_g": float(lk.get("mass_g", 0)),
         "price": None, "search": None, "verified": True, "material": lk.get("material", "PETG"), "dims_mm": lk["dims_mm"]}
        for lk in plan["links"]
        if lk.get("source") == "designed"
    ]
    return [*rows.values(), *printed]


def wiring(plan: dict[str, Any]) -> dict[str, Any]:
    """Nodes (electrical parts) and typed edges (power / data) from the parts' kinds."""
    nodes = [{"id": lk["name"], "kind": part["kind"], "part": part["id"], "name": part["name"]} for lk, part in _bought(plan) if part and part["kind"] in ELECTRIC]
    of = lambda kind: [n["id"] for n in nodes if n["kind"] == kind]  # noqa: E731
    edges: list[dict[str, str]] = []

    def link(a: str, b: str, kind: str) -> None:
        edges.append({"from": a, "to": b, "type": kind})

    boards, drivers, batteries = of("board"), of("driver"), of("battery")
    chain = [*batteries[:1]]
    for step in ("switch", "regulator"):
        chain += of(step)[:1] if step == "regulator" else of(step)
    for a, b in zip(chain, chain[1:], strict=False):
        link(a, b, "power")
    supply = chain[-1] if chain else None
    for board in boards[:1]:
        if supply:
            link(supply, board, "power")
        for drv in drivers:
            link(board, drv, "data")
        for sensor in of("sensor"):
            link(board, sensor, "data")
            if supply:
                link(supply, sensor, "power")
    for drv in drivers:  # the driver feeds the motors/servos it can move, from the battery side
        if batteries:
            link(batteries[0], drv, "power")
    dc_drv = [n["id"] for n in nodes if n["kind"] == "driver" and CATALOG[n["part"]].get("channels") == 2]
    servo_drv = [n["id"] for n in nodes if n["kind"] == "driver" and CATALOG[n["part"]].get("channels", 0) > 2]
    for i, motor in enumerate(of("dc_motor")):  # two motors per H-bridge module
        target = dc_drv[min(i // 2, len(dc_drv) - 1)] if dc_drv else (boards[0] if boards else None)
        if target:
            link(target, motor, "power")
    for servo in of("servo"):
        target = servo_drv[0] if servo_drv else (boards[0] if boards else None)
        if target:
            link(target, servo, "power")
    return {"nodes": nodes, "edges": edges, "nets": ["GND ortak: tüm parçaların toprağı batarya eksisine bağlanır"]}


def steps(plan: dict[str, Any], wires: dict[str, Any]) -> list[dict[str, str]]:
    """Assembly order: print, mount parents before children, wire, then the checks."""
    out: list[dict[str, str]] = []
    for lk in (lk for lk in plan["links"] if lk.get("source") == "designed"):
        out.append({"phase": "baski", "text": f"{lk['name']} parçasını bas ({lk.get('material', 'PETG')}, {'x'.join(f'{v:g}' for v in lk['dims_mm'])} mm)."})
    by_name = {lk["name"]: lk for lk in plan["links"]}
    depth = lambda lk: 0 if not lk.get("parent") or lk["parent"] not in by_name else 1 + depth(by_name[lk["parent"]])  # noqa: E731
    for lk in sorted(plan["links"], key=depth):
        part = CATALOG.get(str(lk.get("part", "")))
        if lk.get("source") != "bought" or not lk.get("parent"):
            continue
        how = "dört köşesinden M3 vidayla sabitle" if part and part["kind"] in MOUNTED else "yerine tak ve sabitle"
        out.append({"phase": "montaj", "text": f"{lk['name']} ({part['name'] if part else lk.get('role', '')}) → {lk['parent']} üzerine, {how}."})
    for e in wires["edges"]:
        out.append({"phase": "kablolama", "text": f"{e['from']} → {e['to']} ({'güç' if e['type'] == 'power' else 'veri'})."})
    out += [
        {"phase": "test", "text": "Bataryayı bağlamadan önce tüm bağlantıları kısa devre için kontrol et."},
        {"phase": "test", "text": "Tekerlekler havadayken motorları çalıştır; yönleri kontrol et."},
        {"phase": "test", "text": "Acil durdurma düğmesinin gücü kestiğini doğrula."},
    ]
    return out


def package(plan: dict[str, Any]) -> dict[str, Any]:
    wires = wiring(plan)
    rows = parts_list(plan)
    return {
        "parts": rows,
        "wiring": wires,
        "steps": steps(plan, wires),
        "totals": {"mass_g": round(sum(r["qty"] * r["unit_mass_g"] for r in rows), 1), "bought": sum(r["qty"] for r in rows if r["kind"] != "3d_baski"), "printed": sum(1 for r in rows if r["kind"] == "3d_baski"), "price": None},
    }
