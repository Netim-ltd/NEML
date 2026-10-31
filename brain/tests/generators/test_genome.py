# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SPEC 18.2 gate 5: the seed genome validates against the SPEC 13.3 schema."""

import copy
import json
from pathlib import Path

import jsonschema
import pytest
import yaml

GENOME_DIR = Path(__file__).resolve().parents[3] / "hardware" / "genome"


def load_schema():
    return json.loads((GENOME_DIR / "genome.schema.json").read_text(encoding="utf-8"))


def load_genome():
    raw = yaml.safe_load((GENOME_DIR / "quadruped_v2.yaml").read_text(encoding="utf-8"))
    # YAML 1.1 turns an unquoted date into a date object; the schema wants ISO text.
    return json.loads(json.dumps(raw, default=str))


def test_schema_itself_is_valid():
    jsonschema.Draft202012Validator.check_schema(load_schema())


def test_seed_genome_validates():
    jsonschema.validate(load_genome(), load_schema())


def test_seed_genome_is_the_spec_13_3_example():
    genome = load_genome()
    assert genome["genome_id"] == "quadruped_v2"
    assert genome["parent"] == "quadruped_v1@8e2bd40"
    assert genome["morphology"]["total_dof"] == 16
    assert genome["limits"] == {
        "joint_torque_nm_max": 2.5,
        "joint_velocity_rads_max": 6.0,
        "body_current_a_max": 20.0,
        "body_temp_c_max": 70.0,
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda g: g["limits"].update(joint_torque_nm_max_override=99),  # new limit key
        lambda g: g["limits"].pop("body_temp_c_max"),  # dropped limit
        lambda g: g["limits"].update(body_current_a_max=0),  # non positive
        lambda g: g.update(status="retired"),  # not a SPEC 7 status
        lambda g: g["mechanical"].update(material="wood"),
        lambda g: g.update(extra_block={"a": 1}),
        lambda g: g.update(hash="ZZZZ"),
    ],
)
def test_schema_is_strict(mutate):
    genome = copy.deepcopy(load_genome())
    mutate(genome)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(genome, load_schema())


def test_limits_block_is_closed_in_the_schema():
    limits = load_schema()["properties"]["limits"]
    assert limits["additionalProperties"] is False
    assert set(limits["required"]) == set(limits["properties"])
