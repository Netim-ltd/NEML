# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SPEC 4.3 stage 3 for behaviour: hand written behaviour trees, filled by parameters.

One BehaviorTree.CPP v4 XML per skill, written to the path the SPEC 7 `skills`
table stores in `bt_path`. The LLM only ever supplies the parameter object
(SPEC 4.3 stage 2); the tree structure is human authored and the emission is
deterministic - same parameters, same bytes.
"""

from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET  # noqa: S405 - our own output  # nosec B405
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema

_NUMBER = {"type": "number"}


class UnknownSkill(KeyError):
    """skill_key has no hand written tree."""


class ParamError(ValueError):
    """Parameters do not satisfy the skill schema."""


@dataclass(frozen=True)
class BehaviorArtifact:
    skill_key: str
    params: dict[str, Any]
    input_sha256: str  # SPEC 0.6 provenance
    bt_path: Path  # SPEC 7 skills.bt_path
    xml: str


def _fmt(value: Any) -> str:
    return f"{value:.9g}" if isinstance(value, float) else str(value)


def _node(tag: str, children: tuple[ET.Element, ...] = (), **attrs: Any) -> ET.Element:
    el = ET.Element(tag, {k: _fmt(v) for k, v in attrs.items()})
    el.extend(children)
    return el


def _battery_guard(p: Mapping[str, Any]) -> ET.Element:
    return _node("CheckBattery", min_soc=p["min_soc"])


def _schema(**properties: Any) -> dict[str, Any]:
    props = {"min_soc": {"type": "number", "minimum": 0.1, "maximum": 1.0}, **properties}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(props),
        "properties": props,
    }


def _walk_straight(p: Mapping[str, Any]) -> ET.Element:
    return _node(
        "Sequence",
        (
            _battery_guard(p),
            _node("SetGait", gait=p["gait"], speed_mps=p["speed_mps"]),
            _node("WalkDistance", distance_m=p["distance_m"], speed_mps=p["speed_mps"]),
            _node("Stand", duration_s=1.0),
        ),
        name="walk_straight",
    )


def _turn_in_place(p: Mapping[str, Any]) -> ET.Element:
    return _node(
        "Sequence",
        (
            _battery_guard(p),
            _node("TurnInPlace", angle_deg=p["angle_deg"], yaw_rate_rads=p["yaw_rate_rads"]),
            _node("Stand", duration_s=1.0),
        ),
        name="turn_in_place",
    )


def _step_over(p: Mapping[str, Any]) -> ET.Element:
    return _node(
        "Sequence",
        (
            _battery_guard(p),
            _node("ApproachObstacle", height_mm=p["step_height_mm"], speed_mps=p["speed_mps"]),
            _node(
                "RetryUntilSuccessful",
                (_node("StepOver", lift_mm=p["lift_mm"], torque_limit_nm=p["torque_limit_nm"]),),
                num_attempts=p["attempts"],
            ),
        ),
        name="step_over",
    )


def _stand(p: Mapping[str, Any]) -> ET.Element:
    return _node(
        "Sequence",
        (_battery_guard(p), _node("Stand", duration_s=p["duration_s"], stiffness=p["stiffness"])),
        name="stand",
    )


def _carry_payload(p: Mapping[str, Any]) -> ET.Element:
    return _node(
        "Sequence",
        (
            _battery_guard(p),
            _node("CheckPayload", payload_g=p["payload_g"]),
            _node("SetGait", gait=p["gait"], speed_mps=p["speed_mps"]),
            _node("WalkDistance", distance_m=p["distance_m"], speed_mps=p["speed_mps"]),
            _node("Stand", duration_s=1.0),
        ),
        name="carry_payload",
    )


def _climb_small_obstacle(p: Mapping[str, Any]) -> ET.Element:
    return _node(
        "Sequence",
        (
            _battery_guard(p),
            _node(
                "Fallback",
                (
                    _node(
                        "Sequence",
                        (
                            _node("DetectObstacle", max_height_mm=p["max_height_mm"]),
                            _node(
                                "ClimbObstacle",
                                lift_mm=p["lift_mm"],
                                torque_limit_nm=p["torque_limit_nm"],
                                approach_mps=p["approach_mps"],
                            ),
                        ),
                    ),
                    _node("Retreat", distance_m=p["retreat_m"]),
                ),
            ),
        ),
        name="climb_small_obstacle",
    )


# SPEC 11.3 reference manoeuvres plus the SPEC 7 example skill. New trees are
# human work, exactly like new CAD templates (SPEC 12.1).
SKILLS: dict[str, tuple[dict[str, Any], Callable[[Mapping[str, Any]], ET.Element]]] = {
    "M1_straight": (
        _schema(
            distance_m={"type": "number", "minimum": 0.1, "maximum": 20},
            speed_mps={"type": "number", "minimum": 0.05, "maximum": 1.0},
            gait={"enum": ["walk", "trot"]},
        ),
        _walk_straight,
    ),
    "M2_turn": (
        _schema(
            angle_deg={"type": "number", "minimum": -360, "maximum": 360},
            yaw_rate_rads={"type": "number", "minimum": 0.05, "maximum": 2.0},
        ),
        _turn_in_place,
    ),
    "M3_step": (
        _schema(
            step_height_mm={"type": "number", "minimum": 5, "maximum": 120},
            lift_mm={"type": "number", "minimum": 10, "maximum": 160},
            speed_mps={"type": "number", "minimum": 0.05, "maximum": 0.6},
            torque_limit_nm={"type": "number", "minimum": 0.1, "maximum": 2.5},
            attempts={"type": "integer", "minimum": 1, "maximum": 5},
        ),
        _step_over,
    ),
    "M4_stand": (
        _schema(
            duration_s={"type": "number", "minimum": 1, "maximum": 300},
            stiffness={"type": "number", "minimum": 0.1, "maximum": 1.0},
        ),
        _stand,
    ),
    "M5_payload": (
        _schema(
            payload_g={"type": "number", "minimum": 0, "maximum": 2000},
            distance_m={"type": "number", "minimum": 0.1, "maximum": 20},
            speed_mps={"type": "number", "minimum": 0.05, "maximum": 1.0},
            gait={"enum": ["walk", "trot"]},
        ),
        _carry_payload,
    ),
    "climb_small_obstacle": (
        _schema(
            max_height_mm={"type": "number", "minimum": 10, "maximum": 120},
            lift_mm={"type": "number", "minimum": 10, "maximum": 160},
            torque_limit_nm={"type": "number", "minimum": 0.1, "maximum": 2.5},
            approach_mps={"type": "number", "minimum": 0.05, "maximum": 0.6},
            retreat_m=_NUMBER,
        ),
        _climb_small_obstacle,
    ),
}


def input_hash(skill_key: str, params: Mapping[str, Any]) -> str:
    payload = {"skill_key": skill_key, "params": dict(params)}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def render(skill_key: str, params: Mapping[str, Any]) -> str:
    """Behaviour tree XML for these parameters. Pure: no filesystem, no model."""
    if skill_key not in SKILLS:
        raise UnknownSkill(skill_key)
    schema, tree = SKILLS[skill_key]
    try:
        jsonschema.validate(dict(params), schema)
    except jsonschema.ValidationError as exc:
        raise ParamError(f"{skill_key}: {exc.message}") from exc

    root = ET.Element("root", BTCPP_format="4", main_tree_to_execute=skill_key)
    behavior = ET.SubElement(root, "BehaviorTree", ID=skill_key)
    behavior.append(tree(params))
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode") + "\n"


def generate(skill_key: str, params: Mapping[str, Any], out_dir: Path) -> BehaviorArtifact:
    """Write the tree and hand back the bt_path for the SPEC 7 skills row."""
    xml = render(skill_key, params)
    digest = input_hash(skill_key, params)
    out_dir.mkdir(parents=True, exist_ok=True)
    bt_path = out_dir / f"{skill_key}-{digest[:12]}.xml"
    bt_path.write_text(xml, encoding="utf-8")
    return BehaviorArtifact(
        skill_key=skill_key,
        params=dict(params),
        input_sha256=digest,
        bt_path=bt_path,
        xml=xml,
    )
