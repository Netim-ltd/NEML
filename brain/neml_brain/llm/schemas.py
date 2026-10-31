# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""JSON Schemas for SPEC 4.3 stage 2 (parameter fill).

Every schema here is the grammar the decoder is constrained with, so it is also
the last line of defence: `additionalProperties` is false everywhere, every
number is bounded and every choice is an enum. A schema-valid object is by
construction inside the physical/DFM envelope the deterministic template
engines (SPEC 4.3 stage 3) accept.
"""

from typing import Any

# SPEC 4.3 stage 1 - the router may emit one of these and nothing else.
INTENT = [
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


# The mechanical parameters are a CSG recipe (boxes, cylinders, cones, spheres, sketches that are extruded, turned or lofted, tubes, copies
# in rows or circles, mirrors, cut/fuse, then holes, a shell and a rounding): there are no parametric templates, the model describes the
# part and the CAD MCP builds it. Every new field is optional, so a plain boxes-and-cylinders recipe is still valid.
_POS = {
    "type": "array",
    "minItems": 3,
    "maxItems": 3,
    "items": {"type": "number", "minimum": -600, "maximum": 600},
}
_DIM = {"type": "number", "minimum": 0.1, "maximum": 600}
_PT = {"type": "array", "minItems": 2, "maxItems": 3, "items": {"type": "number", "minimum": -600, "maximum": 600}}  # [u, v] or [u, v, bulge]
_OUTLINE = {"type": "array", "minItems": 2, "maxItems": 24, "items": _PT}
_AXIS = {"enum": ["x", "y", "z"]}
_SIDE = {"enum": ["x+", "x-", "y+", "y-", "z+", "z-"]}
_ID = {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_]{0,11}$"}
# (plain ASCII names: a stray "calibration块" cannot be written)
MECH_PARAM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["solids", "steps", "result"],
    "properties": {
        "plan": {"type": "string", "maxLength": 400},  # the model's own short plan, written before the recipe (also the chain-of-thought of the training rows)
        "solids": {
            "type": "array",
            "minItems": 1,
            "maxItems": 30,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "t", "at"],
                "properties": {
                    "id": _ID,
                    "t": {"enum": ["box", "cyl", "sphere", "cone", "prism", "turn", "loft", "pipe", "array", "polar", "mirror"]},
                    "at": _POS,
                    "size": {"type": "array", "minItems": 3, "maxItems": 3, "items": _DIM},
                    "r": _DIM,
                    "h": _DIM,
                    "axis": _AXIS,
                    "r2": {"type": "number", "minimum": 0, "maximum": 600},
                    "ri": _DIM,
                    "plane": {"enum": ["xy", "xz", "yz"]},
                    "pts": _OUTLINE,
                    "pts2": _OUTLINE,
                    "about": {"enum": ["u", "v"]},
                    "angle": {"type": "number", "minimum": 1, "maximum": 360},
                    "path": {"type": "array", "minItems": 2, "maxItems": 12, "items": _POS},
                    "of": _ID,
                    "n": {"type": "integer", "minimum": 2, "maximum": 60},
                    "step": _POS,
                },
            },
        },
        "steps": {
            "type": "array",
            "maxItems": 30,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["op", "a", "b", "out"],
                "properties": {
                    "op": {"enum": ["cut", "fuse"]},
                    "a": _ID,
                    "b": _ID,
                    "out": _ID,
                },
            },
        },
        "result": _ID,
        "features": {
            "type": "array",
            "maxItems": 12,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["f"],
                "properties": {
                    "f": {"enum": ["hole", "shell"]},
                    "kind": {"enum": ["plain", "cbore", "csink", "tap"]},
                    "at": _POS,
                    "axis": _AXIS,
                    "dir": {"enum": ["+", "-"]},
                    "d": {"type": "number", "minimum": 0.5, "maximum": 100},
                    "d2": {"type": "number", "minimum": 0.5, "maximum": 200},
                    "depth": _DIM,
                    "depth2": _DIM,
                    "t": {"type": "number", "minimum": 0.4, "maximum": 50},
                    "open": _SIDE,
                },
            },
        },
        "spec": {
            "type": "array",
            "maxItems": 6,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["axis", "value"],
                "properties": {"axis": _AXIS, "value": {"type": "number", "minimum": 0.1, "maximum": 1200}, "tol": {"type": "number", "minimum": 0.001, "maximum": 50}},
            },
        },
        "round": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "r", "edges"],
            "properties": {
                "kind": {"enum": ["fillet", "chamfer"]},
                "r": {"type": "number", "minimum": 0.2, "maximum": 50},
                "edges": {"enum": ["all", "vertical", "top", "bottom"]},
            },
        },
    },
}

# Bounded by SPEC 13.1 (2 layer,
# >=0603 SMD or THT, <10 MHz digital, 5 V/12 V distribution, <=10 A, <=48 V)
# and by the parts SPEC 13.3 actually lists. Board classes SPEC 13.1 forbids
# (multilayer, RF, impedance controlled, scratch SMPS) have no template id, so
# the model cannot ask for one.
_NET = {"type": "string", "pattern": r"^[A-Za-z0-9_+\-./]{1,24}$"}
_PIN = {
    "type": "array",
    "minItems": 4,
    "maxItems": 4,
    "prefixItems": [
        {"type": "string", "pattern": "^[A-Za-z0-9]{1,4}$"},
        {"type": "string", "pattern": "^[A-Za-z0-9_+./-]{1,20}$"},
        {"enum": ["input", "output", "bidirectional", "passive", "power_in", "power_out", "unspecified"]},  # noqa: E501
        _NET,
    ],
}  # no "items": False: llama.cpp rejects a boolean schema; min/maxItems 4 already bound the tuple
ELEC_PARAM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "parts"],
    "properties": {
        "title": {"type": "string", "maxLength": 60},
        "parts": {
            "type": "array",
            "minItems": 2,
            "maxItems": 60,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["ref", "value", "kind", "package", "pins"],
                "properties": {
                    "ref": {"type": "string", "pattern": "^[A-Z]{1,3}[0-9]{1,3}$"},
                    "value": {"type": "string", "maxLength": 30},
                    "kind": {
                        "enum": ["R", "C", "L", "D", "LED", "IC", "CONN", "MOD", "SW", "Q", "F"]
                    },
                    "package": {"enum": ["0603", "0805", "1206", "2512", "THT"]},
                    "pins": {"type": "array", "minItems": 1, "maxItems": 40, "items": _PIN},
                    "part_number": {"type": "string", "maxLength": 40},
                    "supplier": {"type": "string", "maxLength": 20},
                    "decouples": {"type": "string", "maxLength": 6},
                    "needs_decoupling": {"type": "array", "maxItems": 4, "items": _NET},
                },
            },
        },
        "placement": {
            "type": "object",
            "additionalProperties": {
                "type": "array",
                "minItems": 2,
                "maxItems": 2,
                "items": {"type": "number", "minimum": -1000, "maximum": 1000},
            },
        },
        "size": {
            "type": "array",
            "minItems": 2,
            "maxItems": 2,
            "items": {"type": "number", "minimum": -1000, "maximum": 1000},
        },
        "track_mm": {"type": "number", "minimum": 0.15, "maximum": 1.0},
        "limits": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "max_current_a": {"type": "number", "minimum": 0, "maximum": 10},
                "max_voltage_v": {"type": "number", "minimum": 0, "maximum": 48},
                "max_digital_mhz": {"type": "number", "minimum": 0, "exclusiveMaximum": 10},
            },
        },
    },
}

# Behaviour parameters. The torque/velocity ceilings are the SPEC 13.3 `limits`
# block, which evolution may not raise - the schema is where that is enforced
# before anything reaches a joint.
SKILL_PARAM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["skill_key", "params"],
    "properties": {
        "skill_key": {"type": "string", "maxLength": 64, "pattern": "^[a-z][a-z0-9_]{2,63}$"},
        "params": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "gait": {"enum": ["stand", "crawl", "walk", "trot"]},
                "gait_period_s": {"type": "number", "minimum": 0.2, "maximum": 3.0},
                "duty_factor": {"type": "number", "minimum": 0.3, "maximum": 0.9},
                "step_height_mm": {"type": "number", "minimum": 5, "maximum": 80},
                "step_length_mm": {"type": "number", "minimum": 10, "maximum": 145},
                "joint_torque_nm": {"type": "number", "minimum": 0.1, "maximum": 2.5},
                "joint_velocity_rads": {"type": "number", "minimum": 0.1, "maximum": 6.0},
            },
        },
        "rationale": {"type": "string", "maxLength": 300},
    },
}

# SPEC 4.4: one schema per profile.
SCHEMA_FOR_PROFILE: dict[str, dict[str, Any]] = {
    "param_mech": MECH_PARAM_SCHEMA,
    "param_elec": ELEC_PARAM_SCHEMA,
    "param_skill": SKILL_PARAM_SCHEMA,
}
