# ruff: noqa: E501, S311
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The lab's areas of learning and the remedies a lesson may name.

Each area reads a situation and answers with one tool call
(`{"name", "arguments"}`) or with nothing; the tools are the remedies below. A remedy is only a
*suggestion* shown to the owner: nothing here changes a design by itself.
"""

from __future__ import annotations

from typing import Any

_ASK = {
    "name": "ask_owner",
    "parameters": {
        "type": "object",
        "properties": {"question": {"type": "string"}},
        "required": ["question"],
    },
}


def _tool(tool: str, /, **props: Any) -> dict[str, Any]:
    required = [k for k, v in props.items() if not v.pop("optional", False)]
    return {
        "name": tool,
        "parameters": {"type": "object", "properties": props, "required": required},
    }


_NUM = {"type": "number"}
_STR = {"type": "string"}

DOMAINS: dict[str, dict[str, Any]] = {
    "sim": {
        "label": "Simülasyon",
        "tools": [
            _tool(
                "retry_sim",
                world={"enum": ["flat", "maze", "obstacle_low", "ramp_10deg", "rough_terrain"]},
                duration_s=dict(_NUM),
            ),
            _tool("lower_body_mass", mass_kg=dict(_NUM)),
            _tool("explain_no_active_design"),
            _ASK,
        ],
    },
    "assembly": {
        "label": "Montaj, çarpışma ve denge",
        "tools": [
            _tool("move_part", part=dict(_STR), dx=dict(_NUM), dy=dict(_NUM), dz=dict(_NUM)),
            _tool("resize_part", part=dict(_STR), scale=dict(_NUM)),
            _tool("widen_stance", delta_mm=dict(_NUM)),
            _tool("move_mass_towards_centre", part=dict(_STR), dx=dict(_NUM)),
            _ASK,
        ],
    },
    "import": {
        "label": "GitHub içe aktarma",
        "tools": [
            _tool("refresh_import", repo=dict(_STR)),
            _tool(
                "fetch_missing_files",
                repo=dict(_STR),
                paths={"type": "array", "items": {"type": "string"}},
            ),
            _tool("skip_item", path=dict(_STR)),
            _ASK,
        ],
    },
    "electronics": {
        "label": "Elektronik ve kablolama",
        "tools": [
            _tool("check_wiring", a=dict(_STR), b=dict(_STR)),
            _tool("change_pin", board=dict(_STR), pin=dict(_STR)),
            _tool("add_regulator", rail_v=dict(_NUM)),
            _ASK,
        ],
    },
    "design": {
        "label": "Robot tasarımı (ajan toplantıları)",
        "tools": [
            _tool("add_missing_part", part=dict(_STR)),
            _tool("fix_layout", part=dict(_STR)),
            _tool("add_sensor", kind=dict(_STR)),
            _tool("add_safety_feature", kind=dict(_STR)),
            _tool("strengthen_part", part=dict(_STR)),
            _tool("research", topic=dict(_STR)),
            _ASK,
        ],
    },
    "world": {
        "label": "Simülasyon ortamları (dünyalar)",
        "tools": [
            _tool(
                "add_world",
                template={"enum": ["hobby_garden", "warehouse", "stair_hall"]},
                difficulty=dict(_NUM),
            ),
            _tool("make_world_easier", world=dict(_STR)),
            _tool("check_world_path", world=dict(_STR)),
            _ASK,
        ],
    },
    "structure": {
        "label": "Yapısal analiz (mukavemet, bağlantılar)",
        "tools": [
            _tool("thicken_wall", part=dict(_STR), wall_mm=dict(_NUM)),
            _tool(
                "change_material",
                part=dict(_STR),
                material={"enum": ["PETG", "PA6-CF", "PLA", "ASA"]},
            ),
            _tool("add_ribs", part=dict(_STR), count=dict(_NUM)),
            _tool("shorten_link", part=dict(_STR), length_mm=dict(_NUM)),
            _tool("use_stronger_servo", torque_nm=dict(_NUM)),
            _ASK,
        ],
    },
    "cad": {
        "label": "CAD ve baskı",
        "tools": [
            _tool("adjust_dimension", part=dict(_STR), name=dict(_STR), value=dict(_NUM)),
            _tool("round_edges", part=dict(_STR), radius_mm=dict(_NUM)),
            _tool("split_part", part=dict(_STR)),
            _ASK,
        ],
    },
}
