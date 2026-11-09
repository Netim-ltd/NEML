# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A part drawn as a build123d Python script instead of a CSG recipe.

The model writes a short script that leaves its part in `result`; the CAD server checks and runs it (see mcp_servers/neml_mcp_cad/script.py)
and the numbers come back like a recipe build's. A script that fails, or comes out the wrong size, goes back to the model with the message.

# ponytail: three tries and a bounding-box check only; the structural/DFM loops of the recipe path are not repeated here yet."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)

ATTEMPTS = 3
SIZE_TOL = 0.08  # a built side may be this far from the asked size (relative) before the script goes back
SCRIPT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["plan", "code"],
    "properties": {"plan": {"type": "string", "maxLength": 400}, "code": {"type": "string", "minLength": 20, "maxLength": 4000}},
}
SCRIPT_PROMPT = (
    "Bu parçayı build123d (Python) betiğiyle çiz: '{name}' - {role}. Yaklaşık {dims} mm (x, y, z), malzeme {material}.\n"
    "Önce plan alanına 2-3 cümle yaz (ana gövde, delikler/kabuk/yuvarlama nereye, sabit ölçüler). Sonra code alanına betiği yaz.\n"
    "Kurallar: yalnızca build123d ve math kullan (import satırı gerekmez, `from build123d import *` hazır); dosya, ağ, os yok. Birimler mm. "
    "Sonuç `result` değişkeninde TEK katı gövde olsun. Parçanın kendi çerçevesinin (0,0,0) noktası üst parçaya bağlandığı eklemdir; parça bunun yakınında olsun. "
    "Duvar en az 1.6 mm, vida deliği çapı 3.2 mm. Ölçüler verilen boyutlara uysun.\n"
    "Örnek 1 (delikli plaka):\n"
    "with BuildPart() as p:\n    Box(60, 40, 5)\n    with Locations((20, 10, 0), (-20, 10, 0), (20, -10, 0), (-20, -10, 0)):\n        Hole(radius=1.6)\nresult = p.part\n"
    "Örnek 2 (flanşlı silindir, yuvarlatılmış):\n"
    "with BuildPart() as p:\n    Cylinder(radius=10, height=30)\n    with Locations((0, 0, -15 + 2.5)):\n        Cylinder(radius=18, height=5)\n    Hole(radius=5)\n"
    "result = fillet(p.part.edges().filter_by(GeomType.CIRCLE).sort_by(Axis.Z)[-1], 1)\n"
    "Örnek 3 (L braket): iki kutuyu topla: `a = Box(40, 20, 4); b = Pos(18, 0, 12) * Box(4, 20, 28); result = a + b`.\n"
    "API notları (sık hatalar): sin, cos, pi, sqrt hazır (math.'sız yazılır). `cut`, `fuse`, `union` diye fonksiyon YOK: çıkarmak için `a - b`, birleştirmek için `a + b` "
    "ya da BuildPart içinde `Cylinder(..., mode=Mode.SUBTRACT)`. Konumlamak için `Pos(x, y, z) * şekil`, döndürmek için `Rot(0, 0, açı_derece) * şekil` "
    "(Rot bir `with` bloğu değildir; blok için `with Locations(Pos(..) * Rot(..)):`). Köşe yuvarlama: `fillet(parça.edges().filter_by(...), radius=r)` "
    "(ilk argüman kenar listesi; r en fazla en ince duvarın yarısı, emin değilsen 0.8). Kabuk/içi boş kutu: `Box(w, d, h) - Pos(0, 0, t) * Box(w - 2*t, d - 2*t, h)`. "
    "Hacim hedefe yakın olsun: gereksiz boşluk ya da dolgu ekleme.{rules}{error}"
)

KEEP = 60  # scripts remembered; the oldest fall out
NL = chr(10)
WORD = re.compile(r"[a-zçğıöşü0-9]+")


def _book(root: Path) -> list[dict[str, Any]]:
    try:
        return list(json.loads((root / "good_scripts.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return []


def remember(root: Path, role: str, dims: list[float], code: str) -> None:
    """A script that built the right size is kept as an example for the next similar part."""
    rows = [r for r in _book(root) if r["code"] != code]
    rows.append({"role": role[:80], "dims": [round(float(d), 1) for d in dims], "code": code[:4000]})
    (root / "good_scripts.json").write_text(json.dumps(rows[-KEEP:], ensure_ascii=False), encoding="utf-8")


def examples(root: Path, role: str, dims: list[float], n: int = 2) -> str:
    """The n kept scripts closest to this part (shared words of the role, then size), as prompt text; empty when none."""
    words = set(WORD.findall(role.lower()))
    want = sorted(float(d) for d in dims)

    def far(r: dict[str, Any]) -> tuple[int, float]:
        got = sorted(r["dims"])
        return -len(words & set(WORD.findall(r["role"].lower()))), sum(abs(a - b) / max(b, 1.0) for a, b in zip(got, want, strict=False))

    best = sorted(_book(root), key=far)[:n]
    return "".join(f"{NL}Bu lab'da çalışmış benzer betik ({r['role']}, {' x '.join(f'{d:g}' for d in r['dims'])} mm):{NL}{r['code']}" for r in best)


async def build_script(gen: Any, lk: dict[str, Any], out: Path, progress: Any, rules: list[str] | None = None) -> dict[str, Any]:
    """Same contract as `Generator._part`: the built part (volume_mm3, bbox, stl, step, ...) or RuntimeError."""
    from neml_brain.evolution.generative import slug

    name = slug(str(lk["name"]))
    learned = "".join(f" Öğrenilmiş kural: {r}" for r in (gen.rules if rules is None else rules))
    want = sorted(float(v) for v in lk["dims_mm"])
    error = ""
    root = gen._learn.root  # noqa: SLF001
    shown = examples(root, str(lk["role"]), list(lk["dims_mm"]))
    for attempt in range(ATTEMPTS):
        progress(f"{name}: betik {attempt + 1}")
        said = await gen._llm.fill(  # noqa: SLF001
            SCRIPT_PROMPT.format(name=name, role=lk["role"], dims=" x ".join(f"{v:g}" for v in lk["dims_mm"]), material=lk.get("material", "PETG"), rules=learned, error=error) + shown,
            SCRIPT_SCHEMA,
            profile="param_skill",
            max_tokens=1500,
        )
        code = str(said["code"])
        try:
            built = await gen._mcp.call("freecad", "run_script", {"source": code, "out_dir": str(out), "name": name}, 120)  # noqa: SLF001
        except Exception as exc:  # noqa: BLE001 - the CAD server's message is exactly what the model needs
            log.info("script.failed", part=name, attempt=attempt, error=str(exc)[:160])
            error = f"\n\nÖnceki betik çalışmadı: {str(exc)[:300]}. Düzelt."
            continue
        x0, y0, z0, x1, y1, z1 = built["bbox"]
        got = sorted([x1 - x0, y1 - y0, z1 - z0])
        off = [(g, w) for g, w in zip(got, want, strict=True) if w and abs(g - w) / w > SIZE_TOL]
        if off and attempt < ATTEMPTS - 1:
            error = f"\n\nÖnceki betiğin kutusu {' x '.join(f'{g:.1f}' for g in got)} mm çıktı (sıralı), {' x '.join(f'{w:g}' for w in want)} mm olmalı. Düzelt."
            continue
        built["script"] = code
        if not off:
            remember(root, str(lk["role"]), list(lk["dims_mm"]), code)
        built["plan"] = str(said.get("plan", ""))[:400]
        return dict(built)
    raise RuntimeError(f"{name}: betikle parça üretilemedi ({error[-160:]})")
