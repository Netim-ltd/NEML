# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-robot-model and lab-wide settings the owner enters on the admin screen.

A value that differs from model to model (MTBF, service interval, ...) is a
setting, not a constant in code. Each field says whether it is `required`
(the system will not act on that decision until it is set - it never invents a
number) or `recommended` (a documented default applies until it is set).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

LAB = "_lab"  # pseudo-model that carries the lab-wide fields
MATERIALS = ("PLA", "PETG", "ASA", "PA6-CF")


@dataclass(frozen=True, slots=True)
class Field:
    key: str
    label_tr: str
    label_en: str
    unit: str
    level: Literal["required", "recommended"]
    minimum: float
    maximum: float
    help_tr: str
    default: float | None = None  # only a `recommended` field may carry one
    integer: bool = False


MODEL_FIELDS: tuple[Field, ...] = (
    Field(
        "mtbf_min_hours",
        "En düşük kabul edilen MTBF",
        "Minimum acceptable MTBF",
        "saat",
        "required",
        1,
        100_000,
        "İki arıza arası ortalama çalışma süresi bunun altına inerse robot için bakım "
        "görevi açılır. Üreticiden ya da kendi ölçümünden alın; boşken bu karar verilmez.",
    ),
    Field(
        "service_interval_hours",
        "Periyodik bakım aralığı",
        "Service interval",
        "saat",
        "recommended",
        1,
        100_000,
        "Bu kadar çalışma saatinde bakım görevi açılır.",
        default=200,
    ),
    Field(
        "calibration_max_days",
        "Kalibrasyon geçerlilik süresi",
        "Calibration validity",
        "gün",
        "recommended",
        1,
        365,
        "Kalibrasyon bu günden eskiyse yeniden kalibrasyon görevi açılır.",
        default=7,
        integer=True,
    ),
    Field(
        "reality_gap_max",
        "En yüksek reality gap",
        "Maximum reality gap",
        "oran",
        "recommended",
        0.01,
        1.0,
        "Bunun üstünde evrim durur, fizik yeniden kalibre edilir (§11.3).",
        default=0.15,
    ),
    Field(
        "battery_capacity_wh",
        "Batarya kapasitesi",
        "Battery capacity",
        "Wh",
        "recommended",
        1,
        10_000,
        "Şarj ve süre tahminleri için.",
    ),
    Field(
        "max_payload_kg",
        "Azami yük",
        "Maximum payload",
        "kg",
        "recommended",
        0,
        500,
        "Görev planlayıcı bunun üstündeki yük görevlerini reddeder.",
    ),
)

LAB_FIELDS: tuple[Field, ...] = tuple(
    Field(
        f"filament_try_per_kg_{m.lower().replace('-', '_')}",
        f"{m} filament fiyatı",
        f"{m} filament price",
        "TRY/kg",
        "required",
        1,
        100_000,
        "Baskı maliyet tahmini ve bütçe için; dilimleyici profilindeki fiyatla aynı olmalı.",
    )
    for m in MATERIALS
)


def fields_for(model_id: str) -> tuple[Field, ...]:
    return LAB_FIELDS if model_id == LAB else MODEL_FIELDS


def validate(model_id: str, values: dict[str, Any]) -> list[str]:
    """Errors for unknown keys and out-of-range numbers. Missing fields are not
    errors here; `describe` reports them so the screen can show what is open."""
    known = {f.key: f for f in fields_for(model_id)}
    errors = [f"{key}: unknown field" for key in values if key not in known]
    for key, value in values.items():
        field = known.get(key)
        if field is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"{key}: number expected")
        elif not field.minimum <= value <= field.maximum:
            errors.append(f"{key}: must be between {field.minimum} and {field.maximum}")
        elif field.integer and float(value) != int(value):
            errors.append(f"{key}: whole number expected")
    return errors


def describe(model_id: str, values: dict[str, Any]) -> dict[str, Any]:
    """What the admin screen renders: every field, its value and its state."""
    rows = []
    for f in fields_for(model_id):
        value = values.get(f.key)
        state = (
            "ok"
            if value is not None
            else (
                "missing_required"
                if f.level == "required"
                else ("default" if f.default is not None else "missing_recommended")
            )
        )
        rows.append(
            {
                "key": f.key,
                "label_tr": f.label_tr,
                "label_en": f.label_en,
                "unit": f.unit,
                "level": f.level,
                "min": f.minimum,
                "max": f.maximum,
                "help_tr": f.help_tr,
                "default": f.default,
                "integer": f.integer,
                "value": value,
                "state": state,
            }
        )
    return {
        "model_id": model_id,
        "fields": rows,
        "missing_required": [r["key"] for r in rows if r["state"] == "missing_required"],
    }


def effective(model_id: str, values: dict[str, Any]) -> dict[str, float | None]:
    """Stored value, else the recommended default, else None (decision withheld)."""
    return {f.key: values.get(f.key, f.default) for f in fields_for(model_id)}
