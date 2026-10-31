# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where does each part of a robot sit, and how does it move? Read it from the URDF/xacro it ships.

Open-source robot repositories store every part in the frame of its own link; the assembly lives in
the URDF: joints place a child link relative to its parent, each link's visuals place meshes (or
boxes, cylinders, spheres) in the link. This module expands the xacro, walks the joint tree and
returns

  * `placements`: every visual in the zero pose - the mesh file or the primitive, its link, its
    pose in the link frame and in the world (millimetres, quaternions), the unit factor, the colour;
  * `rig`: the joint tree (type, axis, limits, mimic) the 3D viewer needs to pose the robot, and
    `link_matrices` which poses it (the same maths as the viewer's rig.js, tested against it).

xacro support: property (value, block, scope=parent/global), macro (defaults, `*` and `**` block
parameters), calls, if/unless, include and `load_yaml` (resolved by the caller from the
repository), arg, insert_block, element, attribute, `${...}` expressions (arithmetic, comparisons,
`a if c else b`, lists, dicts, subscripts, YAML attribute access, a few math functions) and
`$(arg|find|optenv|env|eval|dirname|cwd|anon ...)`. Not supported (reported, never guessed): YAML
properties without `load_yaml`, Python methods in expressions.

Safety: the text is data. DTD/entities are refused, expressions are evaluated by a whitelisted AST
walker (arithmetic, a few math functions, comparisons - no attribute access, no other calls), sizes,
include count and expansion depth are capped.
"""

from __future__ import annotations

import ast
import math
import re
import xml.etree.ElementTree as ET  # noqa: S405 - DTD/entities are refused before parsing
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Any

import numpy as np
import yaml

MAX_BYTES = 512 * 1024
MAX_NODES = 60_000
MAX_DEPTH = 24
MAX_INCLUDES = 16
MAX_VISUALS = 400
MAX_JOINTS = 250
XACRO_NS = ("http://www.ros.org/wiki/xacro", "http://ros.org/wiki/xacro")
EXPR = re.compile(r"\$\{([^}]*)\}")
SUBSTITUTION = re.compile(r"\$\(([^)]*)\)")

FUNCTIONS: dict[str, Callable[..., Any]] = {
    "str": str,
    "int": int,
    "float": float,
    "len": len,
    "pow": pow,
    "floor": math.floor,
    "ceil": math.ceil,
    "exp": math.exp,
    "log": math.log,
    "asin": math.asin,
    "acos": math.acos,
    "fabs": math.fabs,
    "copysign": math.copysign,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "atan": math.atan,
    "atan2": math.atan2,
    "sqrt": math.sqrt,
    "radians": math.radians,
    "degrees": math.degrees,
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
}
CONSTANTS = {"pi": math.pi, "True": True, "False": False}

# resolver(filename, base_path) -> (repository path, text) | None
Resolver = Callable[[str, str], tuple[str, str] | None]
Blocks = dict[
    str, tuple[ET.Element, dict[str, Any], bool]
]  # element, its scope, insert its children only


class UrdfError(ValueError):
    """The file is not a URDF/xacro this module can safely or fully read."""


class Yaml:
    """A loaded YAML mapping: `${cfg.arm.length}` and `${cfg['arm']['length']}` both work."""

    def __init__(self, data: Any) -> None:
        self.data = data

    def get(self, key: Any) -> Any:
        if isinstance(self.data, dict) and key in self.data:
            return wrap_yaml(self.data[key])
        if (
            isinstance(self.data, list)
            and isinstance(key, int)
            and -len(self.data) <= key < len(self.data)
        ):
            return wrap_yaml(self.data[key])
        raise UrdfError(f"yaml has no '{key}'")


def wrap_yaml(value: Any) -> Any:
    return Yaml(value) if isinstance(value, dict | list) else value


def convert(value: str) -> Any:
    """xacro semantics: 'true'/'false' are booleans, numeric text is a number."""
    low = value.strip().lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return float(value)
    except ValueError:
        return value


def evaluate(
    expr: str, scope: dict[str, Any], extra: dict[str, Callable[..., Any]] | None = None
) -> Any:
    """A xacro expression: arithmetic, comparisons and a few functions over the scope, nothing else."""
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as exc:
        raise UrdfError(f"expression '{expr[:40]}' is not understood") from exc

    def ev(node: ast.AST) -> Any:  # noqa: C901, PLR0911, PLR0912 - one branch per allowed node type
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float | str | bool):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in scope:
                return scope[node.id]
            if node.id in CONSTANTS:
                return CONSTANTS[node.id]
            raise UrdfError(f"unknown name '{node.id}'")
        if isinstance(node, ast.UnaryOp):
            v = ev(node.operand)
            if isinstance(node.op, ast.USub):
                return -v
            if isinstance(node.op, ast.UAdd):
                return +v
            if isinstance(node.op, ast.Not):
                return not v
        if isinstance(node, ast.BinOp):
            a, b = ev(node.left), ev(node.right)
            ops: dict[type, Callable[[Any, Any], Any]] = {
                ast.Add: lambda x, y: x + y,
                ast.Sub: lambda x, y: x - y,
                ast.Mult: lambda x, y: x * y,
                ast.Div: lambda x, y: x / y,
                ast.FloorDiv: lambda x, y: x // y,
                ast.Mod: lambda x, y: x % tuple(y) if isinstance(y, list) else x % y,
                ast.Pow: lambda x, y: x**y if abs(y) <= 16 else math.inf,
            }
            if type(node.op) in ops:
                return ops[type(node.op)](a, b)
        if isinstance(node, ast.Compare):
            compare: dict[type, Callable[[Any, Any], bool]] = {
                ast.Eq: lambda x, y: x == y,
                ast.NotEq: lambda x, y: x != y,
                ast.Lt: lambda x, y: x < y,
                ast.LtE: lambda x, y: x <= y,
                ast.Gt: lambda x, y: x > y,
                ast.GtE: lambda x, y: x >= y,
            }
            compare[ast.In] = lambda x, y: x in y
            compare[ast.NotIn] = lambda x, y: x not in y
            left = ev(node.left)
            for op, right_node in zip(node.ops, node.comparators, strict=True):
                test = compare.get(type(op))
                if test is None:
                    raise UrdfError("comparison not supported")
                right = ev(right_node)
                if not test(left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.BoolOp):
            vals = [ev(v) for v in node.values]
            return all(vals) if isinstance(node.op, ast.And) else any(vals)
        if isinstance(node, ast.IfExp):
            return ev(node.body) if ev(node.test) else ev(node.orelse)
        if isinstance(node, ast.List | ast.Tuple):
            return [ev(e) for e in node.elts]
        if isinstance(node, ast.Dict):
            return {
                ev(k): ev(v) for k, v in zip(node.keys, node.values, strict=True) if k is not None
            }
        if isinstance(node, ast.Subscript):
            base, key = ev(node.value), ev(node.slice)
            if isinstance(base, Yaml):
                return base.get(key)
            if isinstance(base, dict | list | tuple | str):
                try:
                    return wrap_yaml(base[key])
                except (KeyError, IndexError, TypeError) as exc:
                    raise UrdfError(f"'{expr[:40]}': no such item") from exc
        if isinstance(node, ast.Attribute):
            base = ev(node.value)
            if isinstance(base, Yaml):  # attribute access is for loaded YAML only
                return base.get(node.attr)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            fn = (extra or {}).get(node.func.id) or FUNCTIONS.get(node.func.id)
            if fn is not None:
                return fn(*(ev(a) for a in node.args))
        raise UrdfError(f"'{expr[:40]}' uses something xacro-math does not allow")

    return ev(tree)


def local(tag: str) -> tuple[str, bool]:
    """(name without namespace, is it a xacro element)."""
    if tag.startswith("{"):
        ns, _, name = tag[1:].partition("}")
        return name, ns in XACRO_NS
    return tag, False


def fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        text = repr(round(value, 9))
        return text.rstrip("0").rstrip(".") if "e" not in text else repr(value)
    return str(value)


def parse_xml(text: str) -> ET.Element:
    data = text.encode("utf-8", errors="replace")
    if len(data) > MAX_BYTES:
        raise UrdfError("file is too large")
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise UrdfError("DTD/entity declarations are refused")
    try:
        root = ET.fromstring(data)  # noqa: S314 - DTD/entities refused above
    except ET.ParseError as exc:
        raise UrdfError(f"not valid XML ({exc})") from exc
    if local(root.tag)[0] != "robot":
        raise UrdfError("the root element is not <robot>")
    return root


class Expander:
    """xacro: property, macro (defaults, block parameters), calls, if/unless, include, arg, insert_block."""

    def __init__(self, resolver: Resolver | None = None, base: str = "") -> None:
        self.resolver = resolver
        self.base = base  # repository path of the file being expanded (for relative includes)
        self.macros: dict[str, tuple[list[tuple[str, str | None]], list[str], ET.Element]] = {}
        self.args: dict[str, str] = {}
        self.block_props: Blocks = {}
        self.root_scope: dict[str, Any] = {}
        self.nodes = 0
        self.includes = 0
        self.included: list[str] = []

    def functions(self) -> dict[str, Callable[..., Any]]:
        return {"load_yaml": self._load_yaml}

    def _load_yaml(self, filename: str) -> Yaml:
        found = self.resolver(str(filename), self.base) if self.resolver else None
        if found is None:
            raise UrdfError(f"yaml '{str(filename)[-60:]}' was not found in the repository")
        if len(found[1]) > 256 * 1024:
            raise UrdfError("yaml file is too large")
        try:
            data = yaml.safe_load(found[1])
        except yaml.YAMLError as exc:
            raise UrdfError("yaml is not valid") from exc
        return Yaml(data if isinstance(data, dict | list) else {})

    def subst(self, text: str, scope: dict[str, Any]) -> str:
        text = self.subst_commands(text, scope)  # $(find ...) and friends first, as xacro does
        return EXPR.sub(lambda m: fmt(evaluate(m.group(1), scope, self.functions())), text)

    def subst_commands(self, text: str, scope: dict[str, Any]) -> str:
        return SUBSTITUTION.sub(lambda m: self._command(m, scope), text) if "$(" in text else text

    def value(self, text: str, scope: dict[str, Any]) -> Any:
        """A property or parameter value: a lone ${expr} keeps its object (a loaded YAML, a list)."""
        whole = re.fullmatch(r"\$\{([^}]*)\}", self.subst_commands(text, scope).strip())
        if whole:
            result = evaluate(whole.group(1), scope, self.functions())
            return convert(result) if isinstance(result, str) else result
        return convert(self.subst(text, scope))

    def _command(self, match: re.Match[str], scope: dict[str, Any]) -> str:
        words = match.group(1).split()
        if not words:
            raise UrdfError("empty $( ) substitution")
        name, rest = words[0], words[1:]
        if name == "arg" and rest:
            if rest[0] not in self.args:
                raise UrdfError(f"$(arg {rest[0]}) has no default")
            return self.args[rest[0]]
        if name == "find" and rest:
            return f"package://{rest[0]}"
        if name == "optenv" and rest:
            return " ".join(rest[1:])  # the environment is not read: the default always applies
        if name == "env":
            return ""  # the environment is not read
        if name == "eval" and rest:
            return fmt(evaluate(" ".join(rest), scope, self.functions()))
        if name == "dirname":
            return str(PurePosixPath(self.base).parent)
        if name == "cwd":
            return "."
        if name == "anon" and rest:
            return f"anon_{rest[0]}"
        raise UrdfError(f"$({name} ...) is not supported")

    def expand(self, source: ET.Element) -> ET.Element:
        out = ET.Element(
            "robot",
            {
                k: self.subst(v, {})
                for k, v in source.attrib.items()
                if "{" not in k and "xmlns" not in k
            },
        )
        self._children(source, out, self.root_scope, 0, {})
        return out

    def _children(
        self, src: ET.Element, out: ET.Element, scope: dict[str, Any], depth: int, blocks: Blocks
    ) -> None:
        if depth > MAX_DEPTH:
            raise UrdfError("macro nesting is too deep")
        for child in src:
            self._one(child, out, scope, depth, blocks)

    def _one(
        self, child: ET.Element, out: ET.Element, scope: dict[str, Any], depth: int, blocks: Blocks
    ) -> None:
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise UrdfError("the file expands to too many elements")
        name, is_xacro = local(child.tag)
        if is_xacro:
            self._xacro(name, child, out, scope, depth, blocks)
            return
        copy = ET.SubElement(out, name, {k: self.subst(v, scope) for k, v in child.attrib.items()})
        if child.text and child.text.strip():
            copy.text = self.subst(child.text.strip(), scope)
        self._children(child, copy, scope, depth, blocks)

    def _xacro(
        self,
        name: str,
        el: ET.Element,
        out: ET.Element,
        scope: dict[str, Any],
        depth: int,
        blocks: Blocks,
    ) -> None:
        if name == "property":
            key = el.get("name", "")
            if len(el) and "value" not in el.attrib:  # a block property, inserted with insert_block
                self.block_props[key] = (el[0], dict(scope), False)
                return
            if "value" not in el.attrib:
                raise UrdfError(f"property '{key}' has no value")
            target = scope
            where = el.get("scope")
            if where == "global":
                target = self.root_scope
            elif where == "parent":
                target = scope.get("__parent__", scope)
            target[key] = self.value(el.get("value", ""), scope)
        elif name == "arg":
            self.args.setdefault(el.get("name", ""), self.subst(el.get("default", ""), scope))
        elif name == "macro":
            params: list[tuple[str, str | None]] = []
            block_names: list[str] = []
            for token in (el.get("params") or "").split():
                if token.startswith("*"):
                    block_names.append(token)  # '*name' inserts the block, '**name' its children
                    continue
                key, sep, default = token.partition(":=")
                params.append((key, default if sep else None))
            self.macros[el.get("name", "")] = (params, block_names, el)
        elif name in ("if", "unless"):
            cond = convert(self.subst(el.get("value", ""), scope))
            if bool(cond) == (name == "if"):
                self._children(el, out, scope, depth, blocks)
        elif name == "insert_block":
            block = blocks.get(el.get("name", "")) or self.block_props.get(el.get("name", ""))
            if block is None:
                raise UrdfError(f"insert_block: no block named '{el.get('name', '')}'")
            if block[2]:
                self._children(block[0], out, block[1], depth, blocks)  # '**': the children
            else:
                self._one(block[0], out, block[1], depth, blocks)  # evaluated where it was written
        elif name == "element":
            raw_name = (
                el.get("{" + XACRO_NS[0] + "}name")
                or el.get("{" + XACRO_NS[1] + "}name")
                or el.get("name")
                or ""
            )
            tag = self.subst(raw_name, scope)
            if not tag or not re.fullmatch(r"[A-Za-z_][\w.-]*", tag):
                raise UrdfError("xacro:element needs a valid name")
            used = next((k for k in el.attrib if k.startswith("{") and k.endswith("}name")), "name")
            made = ET.SubElement(
                out, tag, {k: self.subst(v, scope) for k, v in el.attrib.items() if k != used}
            )
            self._children(el, made, scope, depth, blocks)
        elif name == "attribute":
            key = self.subst(el.get("name", ""), scope)
            if not re.fullmatch(r"[A-Za-z_][\w.-]*", key):
                raise UrdfError("xacro:attribute needs a valid name")
            out.set(key, self.subst(el.get("value", ""), scope))
        elif name == "include":
            self._include(el, out, scope, depth)
        elif name in self.macros:
            params, block_names, macro = self.macros[name]
            inner = dict(scope)
            inner["__parent__"] = scope
            for key, fallback in params:
                raw = el.get(key, fallback)
                if raw is None:
                    raise UrdfError(f"macro {name}: parameter '{key}' is missing")
                inner[key] = self.value(raw, scope)
            given = list(el)
            if len(given) < len(block_names):
                raise UrdfError(f"macro {name}: {len(block_names)} block parameter(s) expected")
            inner_blocks = {
                **blocks,
                **{
                    b.lstrip("*"): (given[i], scope, b.startswith("**"))
                    for i, b in enumerate(block_names)
                },
            }
            self._children(macro, out, inner, depth + 1, inner_blocks)
        else:
            raise UrdfError(f"xacro:{name} is not supported")

    def _include(self, el: ET.Element, out: ET.Element, scope: dict[str, Any], depth: int) -> None:
        filename = self.subst(el.get("filename", ""), scope)
        self.includes += 1
        if self.includes > MAX_INCLUDES:
            raise UrdfError("too many includes")
        found = self.resolver(filename, self.base) if self.resolver else None
        if found is None:
            raise UrdfError(f"include '{filename[-60:]}' was not found in the repository")
        path, text = found
        self.included.append(path)
        previous, self.base = self.base, path
        try:
            self._children(parse_xml(text), out, scope, depth + 1, {})
        finally:
            self.base = previous


def expand(
    text: str, resolver: Resolver | None = None, base: str = ""
) -> tuple[ET.Element, list[str]]:
    """(the plain URDF tree, the repository paths of the files it included)."""
    expander = Expander(resolver, base)
    return expander.expand(parse_xml(text)), expander.included


# ------------------------------------------------------------------ kinematics
def floats(text: str | None, count: int = 3, default: float = 0.0) -> list[float]:
    parts = (text or "").split()
    try:
        values = [float(p) for p in parts]
    except ValueError as exc:
        raise UrdfError(f"'{(text or '')[:30]}' is not a list of numbers") from exc
    return (values + [default] * count)[:count]


def rotation(roll: float, pitch: float, yaw: float) -> np.ndarray:
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]])
    ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
    rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
    return np.asarray(rz @ ry @ rx)  # URDF rpy: fixed-axis roll, pitch, yaw


def transform(origin: ET.Element | None, unit: float = 1.0) -> np.ndarray:
    t = np.eye(4)
    if origin is not None:
        t[:3, :3] = rotation(*floats(origin.get("rpy")))
        t[:3, 3] = np.array(floats(origin.get("xyz"))) * unit
    return t


def quaternion(matrix: np.ndarray) -> list[float]:
    """[x, y, z, w] of a 3x3 rotation matrix."""
    m = matrix
    trace = float(m[0, 0] + m[1, 1] + m[2, 2])
    if trace > 0:
        s = math.sqrt(trace + 1.0) * 2
        q = [(m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, 0.25 * s]
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        q = [0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s]
    elif m[1, 1] > m[2, 2]:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        q = [(m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s]
    else:
        s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        q = [(m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s, (m[1, 0] - m[0, 1]) / s]
    return [round(float(v), 6) for v in q]


def matrix_from_quaternion(q: list[float]) -> np.ndarray:
    x, y, z, w = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def shape_counts(robot: ET.Element) -> dict[str, int]:
    found: dict[str, int] = {}
    for visual in robot.iter("visual"):
        for kind in ("box", "cylinder", "sphere"):
            if visual.find(f"geometry/{kind}") is not None:
                found[kind] = found.get(kind, 0) + 1
    return found


def summary(robot: ET.Element) -> dict[str, Any]:
    joints = robot.findall("joint")
    movable = [j for j in joints if j.get("type") in ("revolute", "continuous", "prismatic")]
    meshes = sorted({m.get("filename", "")[-80:] for m in robot.iter("mesh") if m.get("filename")})
    return {
        "robot": (robot.get("name") or "")[:60],
        "links": len(robot.findall("link")),
        "joints": len(joints),
        "movable_joints": len(movable),
        "meshes": meshes[:10],
        "shapes": shape_counts(robot),
    }


def to_hex(rgba: list[float]) -> str:
    return "#" + "".join(f"{round(min(max(c, 0.0), 1.0) * 255):02x}" for c in rgba[:3])


def material_colors(robot: ET.Element) -> dict[str, str]:
    colors: dict[str, str] = {}
    for material in robot.iter("material"):
        color = material.find("color")
        if material.get("name") and color is not None and color.get("rgba"):
            colors[str(material.get("name"))] = to_hex(floats(color.get("rgba"), 4, 1.0))
    return colors


def rig_of(robot: ET.Element) -> dict[str, Any]:
    """The joint tree the viewer poses (millimetres, quaternions)."""
    links = [str(link.get("name")) for link in robot.findall("link") if link.get("name")]
    children: set[str] = set()
    joints: list[dict[str, Any]] = []
    for joint in robot.findall("joint"):
        p, c = joint.find("parent"), joint.find("child")
        if (
            p is None
            or c is None
            or not p.get("link")
            or not c.get("link")
            or not joint.get("name")
        ):
            continue
        children.add(str(c.get("link")))
        if len(joints) >= MAX_JOINTS:
            continue
        t = transform(joint.find("origin"), 1000.0)
        limit, mimic, axis = joint.find("limit"), joint.find("mimic"), joint.find("axis")
        kind = str(joint.get("type") or "fixed")
        lower = float(limit.get("lower", "0")) if limit is not None else 0.0
        upper = float(limit.get("upper", "0")) if limit is not None else 0.0
        if kind == "continuous":
            lower, upper = -math.pi, math.pi
        ax = np.array(floats(axis.get("xyz") if axis is not None else "1 0 0"))
        norm = float(np.linalg.norm(ax)) or 1.0
        joints.append(
            {
                "name": str(joint.get("name"))[:60],
                "type": kind,
                "parent": str(p.get("link")),
                "child": str(c.get("link")),
                "pos": [round(float(v), 3) for v in t[:3, 3]],
                "quat": quaternion(t[:3, :3]),
                "axis": [round(float(v) / norm, 6) for v in ax],
                "lower": round(lower, 6),
                "upper": round(upper, 6),
                "mimic": (
                    {
                        "joint": str(mimic.get("joint")),
                        "multiplier": float(mimic.get("multiplier", "1")),
                        "offset": float(mimic.get("offset", "0")),
                    }
                    if mimic is not None and mimic.get("joint")
                    else None
                ),
            }
        )
    roots = [name for name in links if name not in children]
    masses: dict[str, dict[str, Any]] = {}  # kg and the centre of mass in the link frame (mm)
    for link in robot.findall("link"):
        inertial = link.find("inertial")
        mass = inertial.find("mass") if inertial is not None else None
        if inertial is None or mass is None or not link.get("name"):
            continue
        try:
            kg = float(mass.get("value", "0"))
        except ValueError:
            continue
        if kg > 0:
            origin_el = inertial.find("origin")
            centre = (
                np.array(floats(origin_el.get("xyz") if origin_el is not None else None)) * 1000.0
            )
            masses[str(link.get("name"))[:60]] = {
                "mass": kg,
                "com": [round(float(v), 3) for v in centre],
            }
    return {
        "root": roots[0] if roots else (links[0] if links else ""),
        "joints": joints,
        "links": masses,
    }


def joint_motion(joint: dict[str, Any], value: float) -> np.ndarray:
    """The extra transform a joint adds at `value` (radians, or metres for prismatic)."""
    t = np.eye(4)
    ax = np.array(joint["axis"], dtype=float)
    if joint["type"] in ("revolute", "continuous"):
        c, s = math.cos(value), math.sin(value)
        x, y, z = ax
        t[:3, :3] = np.array(
            [
                [c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
                [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
                [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)],
            ]
        )
    elif joint["type"] == "prismatic":
        t[:3, 3] = ax * value * 1000.0
    return t


def link_matrices(
    rig: dict[str, Any], values: dict[str, float] | None = None
) -> dict[str, np.ndarray]:
    """World matrices (mm) of every link for the given joint values; mimic joints follow theirs."""
    values = dict(values or {})
    by_child = {j["child"]: j for j in rig["joints"]}
    by_name = {j["name"]: j for j in rig["joints"]}
    world: dict[str, np.ndarray] = {rig["root"]: np.eye(4)}

    def value_of(joint: dict[str, Any], depth: int = 0) -> float:
        m = joint.get("mimic")
        if m and depth < 8:
            other = by_name.get(m["joint"])
            base = value_of(other, depth + 1) if other is not None else 0.0
            return float(m["multiplier"]) * base + float(m["offset"])
        return float(values.get(joint["name"], 0.0))

    def pose(link: str, seen: tuple[str, ...] = ()) -> np.ndarray:
        if link in world:
            return world[link]
        joint = by_child.get(link)
        if joint is None or link in seen:
            world[link] = np.eye(4)
            return world[link]
        origin = np.eye(4)
        origin[:3, :3] = matrix_from_quaternion(joint["quat"])
        origin[:3, 3] = joint["pos"]
        world[link] = (
            pose(joint["parent"], (*seen, link)) @ origin @ joint_motion(joint, value_of(joint))
        )
        return world[link]

    for joint in rig["joints"]:
        pose(joint["child"])
    return world


def placements(robot: ET.Element, rig: dict[str, Any]) -> list[dict[str, Any]]:
    """Every visual in the zero pose: its pose in the link frame (`vpos`, `vquat`) and in the world."""
    colors = material_colors(robot)
    world = link_matrices(rig)
    out: list[dict[str, Any]] = []
    for link in robot.findall("link"):
        name = str(link.get("name"))
        for visual in link.findall("visual"):
            geometry = visual.find("geometry")
            if geometry is None:
                continue
            origin = transform(visual.find("origin"), 1000.0)
            t = world.get(name, np.eye(4)) @ origin
            item: dict[str, Any] = {
                "link": name[:60],
                "vpos": [round(float(v), 3) for v in origin[:3, 3]],
                "vquat": quaternion(origin[:3, :3]),
                "pos": [round(float(v), 3) for v in t[:3, 3]],
                "quat": quaternion(t[:3, :3]),
            }
            color_el = visual.find("material/color")
            material = visual.find("material")
            if color_el is not None and color_el.get("rgba"):
                item["color"] = to_hex(floats(color_el.get("rgba"), 4, 1.0))
            elif material is not None and material.get("name") in colors:
                item["color"] = colors[str(material.get("name"))]
            mesh = geometry.find("mesh")
            box, cyl, sph = geometry.find("box"), geometry.find("cylinder"), geometry.find("sphere")
            if mesh is not None and mesh.get("filename"):
                scale = floats(mesh.get("scale"), 3, 1.0)
                item["mesh"] = (
                    str(mesh.get("filename")).replace("\\", "/").rsplit("/", 1)[-1].lower()
                )
                item["factor"] = round(float(scale[0]) * 1000.0, 6)  # mesh units -> millimetres
                if max(scale) - min(scale) > 1e-9:
                    item["scale3"] = [round(float(s) * 1000.0, 6) for s in scale]
            elif box is not None:
                size = [round(v * 1000.0, 3) for v in floats(box.get("size"), 3, 1.0)]
                item["shape"] = {"type": "box", "size": size}
            elif cyl is not None:
                item["shape"] = {
                    "type": "cylinder",
                    "radius": round(float(cyl.get("radius", "0.05")) * 1000.0, 3),
                    "length": round(float(cyl.get("length", "0.1")) * 1000.0, 3),
                }
            elif sph is not None:
                item["shape"] = {
                    "type": "sphere",
                    "radius": round(float(sph.get("radius", "0.05")) * 1000.0, 3),
                }
            else:
                continue
            out.append(item)
            if len(out) >= MAX_VISUALS:
                return out
    return out


def assemble(
    text: str, resolver: Resolver | None = None, base: str = ""
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], list[str]]:
    """(summary, placements, rig, included files) of a URDF or xacro; UrdfError when unreadable."""
    robot, included = expand(text, resolver, base)
    rig = rig_of(robot)
    return summary(robot), placements(robot, rig), rig, included


def yaml_files_of(text: str) -> list[str]:
    """File names given to load_yaml(...) (so the caller can fetch them first)."""
    return re.findall(r"load_yaml\(\s*['\"]([^'\"]+)['\"]", text)[:MAX_INCLUDES]


def includes_of(text: str) -> list[str]:
    """The file names a xacro includes (a cheap scan so the caller can fetch them first)."""
    return re.findall(r"<xacro:include[^>]*\sfilename=\"([^\"]+)\"", text)[:MAX_INCLUDES]
