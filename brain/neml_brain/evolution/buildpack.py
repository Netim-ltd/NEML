# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""From a designed robot to something a person can build: parts to buy, parts to print, assembly order, wiring, and what still blocks.

All of it is derived from the plan and the catalog (no model text), so it can be trusted exactly as far as the catalog
numbers are. Ordering and printing stay with the owner (level 4): this only prepares the list."""

from __future__ import annotations

from collections import Counter
from typing import Any

from neml_brain.evolution.catalog import CATALOG, OTHER

POWER_IN = {"board": "güç girişi", "driver": "motor güç girişi", "regulator": "giriş"}


def _slug(text: str) -> str:
    from neml_brain.evolution.generative import slug

    return slug(text)


def build_pack(plan: dict[str, Any], built: dict[str, dict[str, Any]], problems: list[str]) -> dict[str, Any]:
    links = plan["links"]
    bought = [lk for lk in links if lk["source"] == "bought"]
    counts = Counter(str(lk.get("part") or OTHER) for lk in bought)
    bom = [
        {
            "part": pid,
            "name": CATALOG[pid]["name"] if pid in CATALOG else "katalogda yok (elle araştır)",
            "qty": qty,
            "kind": CATALOG[pid]["kind"] if pid in CATALOG else "?",
            "verified": bool(CATALOG.get(pid, {}).get("verified")),
        }
        for pid, qty in sorted(counts.items())
    ]
    prints = []
    for lk in links:
        info = built.get(_slug(str(lk["name"])))
        if lk["source"] == "designed" and info:
            prints.append({
                "name": lk["name"], "material": lk.get("material", "PETG"), "volume_cm3": round(info["volume_mm3"] / 1000, 1), "file": f"{_slug(str(lk['name']))}.stl",
                "drawing": f"{_slug(str(lk['name']))}_drawing.svg" if info.get("drawing") else None,
            })
    steps = [f"{p['name']} parçasını {p['material']} ile bas ({p['file']}, {p['volume_cm3']} cm³)" for p in prints]
    for lk in links:  # parents first, as the plan lists them
        if lk["source"] == "bought" and lk.get("parent"):
            part = CATALOG.get(str(lk.get("part")), {})
            how = "döner eklem olarak" if lk["joint"]["type"] == "revolute" else "sabit olarak"
            steps.append(f"{part.get('name', lk['name'])} ({lk['name']}) parçasını {lk['parent']} üzerine {how} monte et (konum {lk['joint']['x']:g},{lk['joint']['y']:g},{lk['joint']['z']:g} mm)")
    kinds: dict[str, list[dict[str, Any]]] = {}
    for lk in bought:
        part = CATALOG.get(str(lk.get("part")))
        if part:
            kinds.setdefault(part["kind"], []).append({**part, "link": lk["name"]})
    wiring: list[str] = []
    batt, stop, sw = kinds.get("battery", []), [p for p in kinds.get("switch", []) if p["id"] == "estop_22mm"], [p for p in kinds.get("switch", []) if p["id"] != "estop_22mm"]
    chain = [p["link"] for p in (*batt[:1], *stop[:1], *sw[:1])]
    if chain:
        wiring.append("güç: " + " → ".join(chain) + " → " + ", ".join(p["link"] for k in ("regulator", "driver", "board") for p in kinds.get(k, [])[:1]))
    board = (kinds.get("board") or [None])[0]
    hub = next((d for d in kinds.get("driver", []) if d["id"] == "pca9685"), board)
    for i, p in enumerate(kinds.get("servo", [])):
        wiring.append(f"{p['link']}: sinyal → {hub['link'] if hub else 'kontrolcü'} kanal {i}, +V ve GND ayrı servo beslemesinden")
    for i, p in enumerate(kinds.get("dc_motor", [])):
        drv = next((d for d in kinds.get("driver", []) if d["id"] in ("tb6612", "l298n")), None)
        wiring.append(f"{p['link']}: {'motor sürücü ' + drv['link'] + ' çıkış ' + str(i % 2 + 1) if drv else 'MOTOR SÜRÜCÜ YOK'}")
    for p in kinds.get("sensor", []):
        wiring.append(f"{p['link']}: I2C/dijital → {board['link'] if board else 'kontrolcü'}")
    unverified = [b["part"] for b in bom if not b["verified"] and b["part"] != OTHER]
    warnings = [f"katalog değerleri {', '.join(unverified)} için doğrulanmadı: sipariş öncesi ölçü ve torku parça sayfasından kontrol et"] if unverified else []
    if OTHER in counts:
        warnings.append("katalogda olmayan parça var; elle ekle")
    for lk in links:  # manufacturing advice and size checks of the printed parts: warnings, the owner decides
        info = built.get(_slug(str(lk["name"]))) or {}
        warnings += [f"{lk['name']}: {f['text']}" for f in info.get("dfm", []) if f["severity"] in ("high", "medium")]
        warnings += [f"{lk['name']}: {c['axis']} boyu {c['measured']} mm, istenen {c['wanted']} ±{c['tol']}" for c in info.get("spec_checks", []) if not c["ok"]]
    pack = {"bom": bom, "print": prints, "steps": steps, "wiring": wiring, "blockers": problems, "warnings": warnings, "ready": not problems and OTHER not in counts}
    pack["markdown"] = to_markdown(plan.get("name", "robot"), pack)
    return pack


def to_markdown(name: str, pack: dict[str, Any]) -> str:
    out = [f"# {name}: yapım paketi", "", "**Durum:** " + ("hazır (sipariş ve baskı onayı sende)" if pack["ready"] else "engelleri var")]
    if pack["blockers"]:
        out += ["", "## Engeller", *(f"- {b}" for b in pack["blockers"])]
    out += ["", "## Satın alınacaklar", *(f"- {b['qty']} × {b['name']} (`{b['part']}`){'' if b['verified'] else ' — doğrulanmadı'}" for b in pack["bom"])]
    out += ["", "## Basılacaklar", *(f"- {p['name']}: {p['material']}, {p['volume_cm3']} cm³ ({p['file']}{', çizim: ' + p['drawing'] if p.get('drawing') else ''})" for p in pack["print"])]
    out += ["", "## Montaj sırası", *(f"{i}. {s}" for i, s in enumerate(pack["steps"], 1))]
    out += ["", "## Kablolama", *(f"- {w}" for w in pack["wiring"])]
    if pack["warnings"]:
        out += ["", "## Uyarılar", *(f"- {w}" for w in pack["warnings"])]
    return chr(10).join(out)
