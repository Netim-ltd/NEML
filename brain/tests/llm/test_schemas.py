# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""T-011: the SPEC 4.3 stage 2 schemas. The mechanical one is a CSG recipe, not a template."""

import jsonschema
import pytest

from neml_brain.llm import schemas

MECH = jsonschema.Draft202012Validator(schemas.MECH_PARAM_SCHEMA)
BAR = {
    "solids": [
        {"id": "bar", "t": "box", "at": [0, 0, 0], "size": [120, 28, 28]},
        {"id": "hole", "t": "cyl", "at": [10, 14, -1], "r": 1.6, "h": 30, "axis": "z"},
    ],
    "steps": [{"op": "cut", "a": "bar", "b": "hole", "out": "part"}],
    "result": "part",
}


def test_intent_list_has_no_campaign_or_skill_tuning_intents():
    assert schemas.INTENT == [
        "create_task",
        "update_task",
        "cancel_task",
        "query_status",
        "query_telemetry",
        "query_skill",
        "mech_param_change",
        "elec_param_change",
        "explain",
        "unknown",
    ]


@pytest.mark.parametrize(
    "schema", [schemas.MECH_PARAM_SCHEMA, schemas.ELEC_PARAM_SCHEMA, schemas.SKILL_PARAM_SCHEMA]
)
def test_every_schema_is_valid_and_closed(schema):
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema.get("additionalProperties") is False


def test_each_param_profile_has_its_own_schema():
    assert set(schemas.SCHEMA_FOR_PROFILE) == {"param_mech", "param_elec", "param_skill"}
    assert len({id(s) for s in schemas.SCHEMA_FOR_PROFILE.values()}) == 3


def test_a_cad_recipe_is_representable():
    assert MECH.is_valid(BAR), list(MECH.iter_errors(BAR))


@pytest.mark.parametrize(
    "bad",
    [
        {"solids": BAR["solids"], "steps": []},  # no result
        {**BAR, "result": 5},
        {**BAR, "tool": "rm -rf"},  # nothing outside the recipe
        {
            **BAR,
            "solids": [{"id": "x", "t": "mesh", "at": [0, 0, 0]}],
        },  # only boxes, cylinders, spheres
        {
            **BAR,
            "solids": [{"id": "x", "t": "box", "at": [0, 0, 0], "size": [4000, 1, 1]}],
        },  # bounded
        {**BAR, "solids": [{"id": "x", "t": "box", "at": [0, 0, 9999], "size": [1, 1, 1]}]},
        {**BAR, "solids": [{"id": "x", "t": "box", "at": [0, 0], "size": [1, 1, 1]}]},
        {**BAR, "steps": [{"op": "exec", "a": "bar", "b": "hole", "out": "p"}]},  # cut or fuse only
        {**BAR, "steps": [{"op": "cut", "a": "bar", "b": "hole", "out": "p", "code": "x"}]},
    ],
)
def test_the_schema_refuses_anything_that_is_not_a_plain_recipe(bad):
    assert not MECH.is_valid(bad)
