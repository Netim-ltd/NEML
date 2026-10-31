# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The four SPEC 12.4 profiles stay consistent with the SPEC 12.3 DFM limits.

The DFM validator rejects geometry against fixed numbers (1.2 mm wall, 0.4 mm
nozzle, 250x210x220 build volume). Those numbers are only true if the slicer
profile can actually realise them, and a profile is one careless edit away from
silently breaking that - drop a structural profile to two perimeters and the
1.2 mm wall stops being solid wall. This is the test that fails first.

    pytest -q manufacturing/slicer_profiles

It sits under tests/ because ruff (S101) and bandit (B101) only exempt asserts on
that path segment, and `pre-commit run --all` is a blocking gate (SPEC 18.2).
"""

from __future__ import annotations

from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent  # manufacturing/slicer_profiles
MIN_WALL_MM = 1.2  # SPEC 12.3
NOZZLE_MM = 0.4  # SPEC 12.3
BUILD_VOLUME_MM = (250.0, 210.0, 220.0)  # SPEC 12.3
SUPPORT_FREE_ANGLE_DEG = 45  # SPEC 12.3

# SPEC 12.4: exactly these four, and the names are the Literal in
# brain/neml_brain/agents/manufacturing.py:SliceRequest.profile.
PROFILES = [
    "petg_0.20_structural",
    "pa6cf_0.20_structural",
    "pla_0.25_draft",
    "asa_0.20_outdoor",
]
STRUCTURAL = [p for p in PROFILES if p.endswith("_structural")]


def load(name: str) -> dict[str, str]:
    """PrusaSlicer config ini: flat key = value, `#` comments, no sections."""
    config: dict[str, str] = {}
    for line in (HERE / f"{name}.ini").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            config[key.strip()] = value.strip()
    return config


def test_exactly_the_four_spec_profiles() -> None:
    assert sorted(p.stem for p in HERE.glob("*.ini")) == sorted(PROFILES)


@pytest.mark.parametrize("name", PROFILES)
def test_printer_matches_the_dfm_limits(name: str) -> None:
    config = load(name)
    assert float(config["nozzle_diameter"]) == NOZZLE_MM
    assert config["bed_shape"] == "0x0,250x0,250x210,0x210"  # 250 x 210 mm
    assert float(config["max_print_height"]) == BUILD_VOLUME_MM[2]
    # "smallest detail >= nozzle diameter" has to hold inside the slicer too.
    assert float(config["min_feature_size"]) >= NOZZLE_MM
    # Supports stay off: DFM rejects the geometry instead of propping it up.
    assert config["support_material"] == "0"
    assert float(config["support_material_threshold"]) == SUPPORT_FREE_ANGLE_DEG


@pytest.mark.parametrize("name", PROFILES)
def test_layer_height_is_printable_and_matches_the_name(name: str) -> None:
    layer = float(load(name)["layer_height"])
    assert 0.05 <= layer <= 0.75 * NOZZLE_MM  # 0.30 mm ceiling on a 0.4 nozzle
    assert f"_{layer:.2f}_" in name  # petg_0.20_structural


@pytest.mark.parametrize("name", STRUCTURAL)
def test_structural_walls_are_solid_at_the_minimum(name: str) -> None:
    """A 1.2 mm wall must come out as perimeters only - no infill inside it."""
    config = load(name)
    perimeters = int(config["perimeters"])
    width = float(config["perimeter_extrusion_width"])
    assert perimeters * width >= MIN_WALL_MM, f"{name}: {perimeters} x {width} mm"


@pytest.mark.parametrize("name", PROFILES)
def test_every_profile_has_the_knob_qc_writes_back_to(name: str) -> None:
    """SPEC 12.5 updates xy_size_compensation automatically after three consecutive
    same-direction deviations. A profile without the key cannot be compensated."""
    value = float(load(name)["xy_size_compensation"])
    assert abs(value) <= 0.5  # mcp_servers.neml_mcp_fab.qc.MAX_COMPENSATION_MM


def test_pa6cf_density_matches_the_genome() -> None:
    """SPEC 13.3 puts PA6-CF at 1.17 g/cm3. If the slicer disagrees, every filament
    weight, every cost and the SPEC 12.5 +/-5% mass check drift together."""
    assert float(load("pa6cf_0.20_structural")["filament_density"]) == 1.17


def test_pa6cf_carries_the_three_mandatory_process_requirements() -> None:
    """SPEC 12.3: hardened nozzle + drying + enclosed chamber."""
    notes = (load("pa6cf_0.20_structural")["filament_notes"]).lower()
    assert "hardened" in notes
    assert "dry" in notes
    assert "enclos" in notes


def test_temperatures_suit_the_stated_purpose() -> None:
    """Outdoor beats draft beats nothing: ASA and PA6 need a hot bed and a cold
    fan, PLA needs the opposite. Swapped profiles fail here."""
    for name in ("pa6cf_0.20_structural", "asa_0.20_outdoor"):
        config = load(name)
        assert float(config["first_layer_bed_temperature"]) >= 100  # warp control
        assert int(config["max_fan_speed"]) <= 20  # layer adhesion over detail
    pla = load("pla_0.25_draft")
    assert int(pla["max_fan_speed"]) == 100
    assert float(pla["temperature"]) < float(load("petg_0.20_structural")["temperature"])
