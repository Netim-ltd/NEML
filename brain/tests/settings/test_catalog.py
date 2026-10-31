# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
from neml_brain.settings import catalog


def test_required_field_is_reported_missing_until_the_owner_sets_it() -> None:
    view = catalog.describe("quadruped_v2", {})
    assert view["missing_required"] == ["mtbf_min_hours"]
    set_view = catalog.describe("quadruped_v2", {"mtbf_min_hours": 400})
    assert set_view["missing_required"] == []


def test_recommended_field_falls_back_to_its_default_and_required_never_does() -> None:
    eff = catalog.effective("quadruped_v2", {})
    assert eff["calibration_max_days"] == 7
    assert eff["mtbf_min_hours"] is None  # a required value is never invented


def test_validation_rejects_unknown_range_and_fractional_integer() -> None:
    assert catalog.validate("quadruped_v2", {"nope": 1}) == ["nope: unknown field"]
    assert catalog.validate("quadruped_v2", {"mtbf_min_hours": 0})
    assert catalog.validate("quadruped_v2", {"calibration_max_days": 2.5})
    assert catalog.validate("quadruped_v2", {"mtbf_min_hours": True})
    assert catalog.validate("quadruped_v2", {"mtbf_min_hours": 300}) == []


def test_lab_fields_carry_one_required_price_per_material() -> None:
    keys = [f.key for f in catalog.LAB_FIELDS]
    assert keys == [f"filament_try_per_kg_{m}" for m in ("pla", "petg", "asa", "pa6_cf")]
    assert all(f.level == "required" for f in catalog.LAB_FIELDS)
