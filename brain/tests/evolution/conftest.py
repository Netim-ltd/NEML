# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared fixtures for the evolution tests: a robot the lab designed (parts made by the CAD MCP)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

ENTRY: dict[str, Any] = {
    "id": "gen_base",
    "kind": "stl",
    "name": "base",
    "file": "base.stl",
    "branch": "",
    "source": "NEML tasarımı",
    "repo": "generated",
    "license": "NEML üretimi",
    "urls": {"stl": "/api/v1/media/aaaaaaaaaaaaaaaaaaaaaaaa.stl"},
    "size": [160.0, 100.0, 40.0],
    "center": [0.0, 0.0, 0.0],
    "design": {"role": "gövde", "material": "PETG", "volume_mm3": 640000 * 0.3},
}
_GENERATED: dict[str, Any] = {
    "schema_version": 1,
    "genome_id": "gezgin",
    "status": "active",
    "morphology": {"body_type": "imported", "leg_count": 0, "dof_per_leg": 0, "total_dof": 1},
    "mechanical": {
        "material": "PETG",
        "body_mass_kg": 1.2,
        "imports": [ENTRY],
        "generated": {
            "brief": "gezgin",
            "purpose": "bahçe",
            "plan": [
                {
                    "name": "base",
                    "source": "designed",
                    "material": "PETG",
                    "dims_mm": [160, 100, 40],
                    "mass_g": 400,
                    "role": "gövde",
                },
                {
                    "name": "motor",
                    "source": "bought",
                    "dims_mm": [30, 20, 20],
                    "mass_g": 60,
                    "role": "tekerlek motoru",
                },
            ],
        },
    },
    "limits": {"joint_torque_nm_max": 2.5},
}


@pytest.fixture
def generated() -> dict[str, Any]:
    return deepcopy(_GENERATED)
