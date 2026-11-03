# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A part drawn as a build123d Python script instead of a CSG recipe.

The model writes a short script that leaves its part in `result`; the CAD server checks and runs it (see mcp_servers/neml_mcp_cad/script.py)
and the numbers come back like a recipe build's. A script that fails, or comes out the wrong size, goes back to the model with the message.

# ponytail: three tries and a bounding-box check only; the structural/DFM loops of the recipe path are not repeated here yet."""

from __future__ import annotations

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
    "Örnek 3 (L braket): iki kutuyu topla: `a = Box(40, 20, 4); b = Pos(18, 0, 12) * Box(4, 20, 28); result = a + b`.{rules}{error}"
)


async def build_script(gen: Any, lk: dict[str, Any], out: Path, progress: Any, rules: list[str] | None = None) -> dict[str, Any]:
    """Same contract as `Generator._part`: the built part (volume_mm3, bbox, stl, step, ...) or RuntimeError."""
    from neml_brain.evolution.generative import slug

    name = slug(str(lk["name"]))
    learned = "".join(f" Öğrenilmiş kural: {r}" for r in (gen.rules if rules is None else rules))
    want = sorted(float(v) for v in lk["dims_mm"])
    error = ""
    for attempt in range(ATTEMPTS):
        progress(f"{name}: betik {attempt + 1}")
        said = await gen._llm.fill(  # noqa: SLF001
            SCRIPT_PROMPT.format(name=name, role=lk["role"], dims=" x ".join(f"{v:g}" for v in lk["dims_mm"]), material=lk.get("material", "PETG"), rules=learned, error=error),
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
        built["plan"] = str(said.get("plan", ""))[:400]
        return dict(built)
    raise RuntimeError(f"{name}: betikle parça üretilemedi ({error[-160:]})")
