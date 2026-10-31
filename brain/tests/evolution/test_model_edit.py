# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The model chat: placing parts of a designed robot and the grammar of its actions."""

from __future__ import annotations

import pytest

from neml_brain.evolution.model_edit import Rejected, action_schema, apply_layout, scene_parts


def test_a_part_is_moved_in_a_copy_and_the_original_is_untouched(generated):
    pid = scene_parts(generated)[0]["id"]
    new, changes = apply_layout(generated, [{"part": pid, "axis": "x", "value": 50}])
    assert new["mechanical"]["layout"][pid]["pos"][0] == 50.0
    assert "layout" not in generated["mechanical"] and changes[0]["new"] == 50


def test_unknown_parts_cad_sizes_and_no_ops_are_refused(generated):
    pid = scene_parts(generated)[0]["id"]
    with pytest.raises(Rejected):
        apply_layout(generated, [{"part": "nope", "axis": "x", "value": 1}])
    with pytest.raises(Rejected, match="yeniden tasarla"):
        apply_layout(
            generated, [{"part": pid, "axis": "sx", "value": 10}]
        )  # a CAD part is resized by designing it again
    current = scene_parts(generated)[0]["pos"][0]
    with pytest.raises(Rejected, match="zaten"):
        apply_layout(generated, [{"part": pid, "axis": "x", "value": current}])


def test_the_action_grammar_offers_the_actions_and_only_the_robots_parts(generated):
    schema = action_schema(generated)
    assert set(schema["properties"]["action"]["enum"]) == {
        "explain",
        "place",
        "redesign",
        "simulate",
        "learn",
        "import",
    }
    parts = {p["id"] for p in scene_parts(generated)}
    assert set(schema["properties"]["placements"]["items"]["properties"]["part"]["enum"]) == parts
    assert "flat" in schema["properties"]["world"]["enum"]
