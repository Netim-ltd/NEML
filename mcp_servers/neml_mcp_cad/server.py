# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""neml-mcp-cad - FreeCAD wrapper, port 9104 (SPEC 6.2 #13).

Builds parts in FreeCAD by running `freecadcmd` as a separate process. There are no parametric
templates: the model describes a part as a declarative CSG recipe (boxes, cylinders, spheres, cut and
fuse, then an optional fillet or chamfer of the edges), the server validates it as data and draws it; nothing the caller sends is executed. FreeCAD is LGPL and
stays outside this tree (SPEC 1.3); no FreeCAD module is imported here.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp_servers._common import CliTimeout, make_app, run_cli

PORT = 9104
VERSION = "1.0.0"
DEFAULT_TIMEOUT_S = 120.0
REPO_ROOT = Path(__file__).resolve().parents[2]

# Runs *inside* freecadcmd, which is the only interpreter that can import FreeCAD.
_DRIVER = (Path(__file__).with_name("freecad_driver.py")).read_text(encoding="utf-8")


class CadError(RuntimeError):
    """Base typed error for every CAD entry point."""


class CadTimeoutError(CadError):
    """freecadcmd did not finish inside the timeout."""


Runner = Callable[[list[str], float], Awaitable[str]]


@dataclass
class _State:
    runner: Runner = run_cli


_S = _State()


def configure(runner: Runner | None = None) -> None:
    if runner is not None:
        _S.runner = runner


async def _freecad(request: dict[str, Any], timeout_s: float) -> Any:
    """One freecadcmd run: write driver + request, run, read the JSON result."""
    with tempfile.TemporaryDirectory(prefix="neml_cad_") as tmp:
        driver = Path(tmp) / "driver.py"
        request_file = Path(tmp) / "request.json"
        result_file = Path(tmp) / "result.json"
        driver.write_text(_DRIVER, encoding="utf-8")
        request["result_path"] = str(result_file)
        request_file.write_text(json.dumps(request), encoding="utf-8")
        argv = [os.getenv("FREECADCMD_BIN", "freecadcmd"), str(driver), str(request_file)]
        try:
            await _S.runner(argv, timeout_s)
        except CliTimeout as exc:
            raise CadTimeoutError(str(exc)) from exc
        except CadError:
            raise
        except Exception as exc:
            raise CadError(f"freecadcmd failed: {type(exc).__name__}: {exc}") from exc
        if not result_file.is_file():
            raise CadError("freecadcmd produced no result file")
        return json.loads(result_file.read_text(encoding="utf-8"))


# --- tools ------------------------------------------------------------------


ALLOWED_ROOTS = (Path("/srv/neml/artifacts"), Path("/srv/neml/work"))
MAX_SOLIDS = 60
MAX_DIM_MM = 600.0
PLANES = ("xy", "xz", "yz")
TAPS = (2, 2.5, 3, 4, 5, 6, 8, 10, 12)
SIDES = tuple(f"{a}{s}" for a in "xyz" for s in "+-")
NAME_RE = r"[a-z0-9_]{1,40}"


def repair_recipe(recipe: dict[str, Any]) -> dict[str, Any]:
    """Mend the slips a small model makes, so the part is not lost to a typo: a step that names an id nobody defined (yet) is dropped,
    a repeated id gets a new name, a missing or unknown `result` becomes the last step's output (or the last solid). Geometry is never touched."""
    solids = [dict(s) for s in recipe.get("solids") or [] if isinstance(s, dict)]
    known: set[str] = set()
    kept = []
    for i, s in enumerate(solids):
        if not isinstance(s.get("id"), str) or s["id"] in known:
            s["id"] = f"s{i}_{len(known)}"
        if s.get("t") in ("array", "polar", "mirror") and s.get("of") not in known:
            continue  # copies of a solid nobody drew
        known.add(s["id"])
        kept.append(s)
    solids = kept
    steps = []
    for st in recipe.get("steps") or []:
        if not isinstance(st, dict) or st.get("a") not in known or st.get("b") not in known:
            continue
        out = st.get("out")
        if not isinstance(out, str) or not out or out in known:
            out = f"r{len(known)}"
        steps.append({**st, "out": out})
        known.add(out)
    result = recipe.get("result")
    if result not in known:
        result = steps[-1]["out"] if steps else solids[-1]["id"] if solids else result
    return {**recipe, "solids": solids, "steps": steps, "result": result}


def _num(value: Any, low: float, high: float, what: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not low <= value <= high:
        raise CadError(f"{what} must be a number in [{low}, {high}]")


def _int(value: Any, low: int, high: int, what: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise CadError(f"{what} must be a whole number in [{low}, {high}]")


def _points(pts: Any, low: int, high: int, what: str) -> None:
    """A sketch outline: [u, v] corners, or [u, v, bulge] where a bulge (tan of a quarter of the arc angle) turns the edge to the next corner into an arc."""
    if not isinstance(pts, list) or not low <= len(pts) <= high:
        raise CadError(f"{what} needs {low}..{high} points")
    for p in pts:
        if not isinstance(p, list) or len(p) not in (2, 3):
            raise CadError(f"{what} points are [u, v] or [u, v, bulge]")
        _num(p[0], -MAX_DIM_MM, MAX_DIM_MM, what)
        _num(p[1], -MAX_DIM_MM, MAX_DIM_MM, what)
        if len(p) == 3:
            _num(p[2], -10, 10, "bulge")


def check_recipe(recipe: dict[str, Any]) -> None:
    """A design recipe is data: solids (boxes, cylinders, cones, spheres, sketches extruded, turned, lofted or piped, copies in rows, circles and mirrors, all in mm)
    combined by cut/fuse steps, then holes and a shell, then a fillet or chamfer. Anything else is refused."""
    solids, steps = recipe.get("solids"), recipe.get("steps", [])
    if not isinstance(solids, list) or not solids or len(solids) + len(steps) > MAX_SOLIDS:
        raise CadError(f"recipe needs 1..{MAX_SOLIDS} solids and steps")
    known: set[str] = set()
    for s in solids:
        if not isinstance(s, dict) or not isinstance(s.get("id"), str) or s["id"] in known:
            raise CadError("every solid needs a unique string id")
        if not (isinstance(s.get("at"), list) and len(s["at"]) == 3):
            raise CadError("`at` must be [x, y, z]")
        for v in s["at"]:
            _num(v, -MAX_DIM_MM, MAX_DIM_MM, "position")
        t = s.get("t")
        if t == "box":
            if not (isinstance(s.get("size"), list) and len(s["size"]) == 3):
                raise CadError("box needs size [l, w, h]")
            for v in s["size"]:
                _num(v, 0.1, MAX_DIM_MM, "box size")
        elif t == "cyl":
            _num(s.get("r"), 0.1, MAX_DIM_MM, "cylinder r")
            _num(s.get("h"), 0.1, MAX_DIM_MM, "cylinder h")
            if s.get("axis") not in ("x", "y", "z"):
                raise CadError("cylinder axis must be x, y or z")
        elif t == "cone":
            _num(s.get("r"), 0.0, MAX_DIM_MM, "cone r")
            _num(s.get("r2"), 0.0, MAX_DIM_MM, "cone r2")
            _num(s.get("h"), 0.1, MAX_DIM_MM, "cone h")
            if s.get("axis") not in ("x", "y", "z") or (s["r"] == 0 and s["r2"] == 0):
                raise CadError("cone needs axis x, y or z and at least one radius above 0")
        elif t == "sphere":
            _num(s.get("r"), 0.1, MAX_DIM_MM, "sphere r")
        elif t in ("prism", "turn", "loft"):
            if s.get("plane", "xy") not in PLANES:
                raise CadError("sketch plane must be xy, xz or yz")
            if s.get("pts") is not None:
                _points(s["pts"], 2 if t == "prism" else 3, 40, "sketch")
            elif t == "prism":
                _num(s.get("r"), 0.1, MAX_DIM_MM, "sketch circle r")
            else:
                raise CadError(f"{t} needs a point outline `pts`")
            if t in ("prism", "loft"):
                _num(s.get("h"), 0.1, MAX_DIM_MM, f"{t} h")
            if t == "turn":
                if s.get("about", "v") not in ("u", "v"):
                    raise CadError("turn about must be u or v")
                _num(s.get("angle", 360), 1, 360, "turn angle")
            if t == "loft":
                _points(s.get("pts2"), len(s["pts"]), len(s["pts"]), "loft top outline")
        elif t == "pipe":
            path = s.get("path")
            if not isinstance(path, list) or not 2 <= len(path) <= 12 or any(not isinstance(p, list) or len(p) != 3 for p in path):
                raise CadError("pipe needs a path of 2..12 [x, y, z] points")
            for p in path:
                for v in p:
                    _num(v, -MAX_DIM_MM, MAX_DIM_MM, "pipe path")
            _num(s.get("r"), 0.1, MAX_DIM_MM, "pipe r")
            if s.get("ri") is not None:
                _num(s["ri"], 0.05, s["r"] - 0.05 if s["r"] > 0.1 else 0.05, "pipe inner r")
        elif t in ("array", "polar", "mirror"):
            if s.get("of") not in known:
                raise CadError(f"{t} copies a solid defined before it (`of`)")
            if t == "array":
                _int(s.get("n"), 2, 30, "array n")
                if not (isinstance(s.get("step"), list) and len(s["step"]) == 3):
                    raise CadError("array needs step [dx, dy, dz]")
                for v in s["step"]:
                    _num(v, -MAX_DIM_MM, MAX_DIM_MM, "array step")
            elif t == "polar":
                _int(s.get("n"), 2, 60, "polar n")
                if s.get("axis") not in ("x", "y", "z"):
                    raise CadError("polar axis must be x, y or z")
                _num(s.get("angle", 360), 1, 360, "polar angle")
            elif s.get("plane") not in PLANES:
                raise CadError("mirror plane must be xy, xz or yz (the plane normal is the third axis)")
        else:
            raise CadError("solid type must be box, cyl, cone, sphere, prism, turn, loft, pipe, array, polar or mirror")
        known.add(s["id"])
    for st in steps:
        if not isinstance(st, dict) or st.get("op") not in ("cut", "fuse") or st.get("a") not in known or st.get("b") not in known or not isinstance(st.get("out"), str):
            raise CadError("a step needs op cut|fuse, known a and b, and an out id")
        known.add(st["out"])
    if recipe.get("result") not in known:
        raise CadError("`result` must name a solid or a step output")
    features = recipe.get("features") or []
    if not isinstance(features, list) or len(features) > 24:
        raise CadError("at most 24 features")
    for f in features:
        if not isinstance(f, dict):
            raise CadError("a feature is an object")
        if f.get("f") == "hole":
            if not (isinstance(f.get("at"), list) and len(f["at"]) == 3) or f.get("axis") not in ("x", "y", "z") or f.get("dir", "-") not in ("+", "-"):
                raise CadError("hole needs at [x, y, z], axis x|y|z and dir + or -")
            for v in f["at"]:
                _num(v, -MAX_DIM_MM, MAX_DIM_MM, "hole position")
            kind = f.get("kind", "plain")
            if kind not in ("plain", "cbore", "csink", "tap"):
                raise CadError("hole kind must be plain, cbore, csink or tap")
            _num(f.get("d"), 0.5, 100, "hole d")
            if f.get("depth") is not None:
                _num(f["depth"], 0.1, MAX_DIM_MM, "hole depth")
            if kind == "tap" and f["d"] not in TAPS:
                raise CadError(f"a tapped hole is one of M{', M'.join(str(t) for t in TAPS)}")
            if kind in ("cbore", "csink"):
                _num(f.get("d2"), f["d"] + 0.1 if isinstance(f.get("d"), int | float) else 0.6, 200, "hole d2")
            if kind == "cbore":
                _num(f.get("depth2"), 0.1, MAX_DIM_MM, "hole depth2")
        elif f.get("f") == "shell":
            _num(f.get("t"), 0.4, 50, "shell t")
            if f.get("open") not in SIDES:
                raise CadError("shell open must be x+, x-, y+, y-, z+ or z-")
        else:
            raise CadError("feature must be hole or shell")
    rd = recipe.get("round")
    if rd is not None:
        if not isinstance(rd, dict) or rd.get("kind") not in ("fillet", "chamfer") or rd.get("edges") not in ("all", "vertical", "top", "bottom"):
            raise CadError("round needs kind fillet|chamfer and edges all|vertical|top|bottom")
        _num(rd.get("r"), 0.2, 50, "round r")
    for d in recipe.get("spec") or []:
        if not isinstance(d, dict) or d.get("axis") not in ("x", "y", "z"):
            raise CadError("spec items are {axis, value, tol}")
        _num(d.get("value"), 0.1, 2 * MAX_DIM_MM, "spec value")
        _num(d.get("tol", 0.5), 0.001, 50, "spec tol")


def _under_roots(path: str) -> Path:
    resolved = Path(path).resolve()
    if not any(root in resolved.parents or root == resolved for root in ALLOWED_ROOTS):
        raise CadError("paths must be under /srv/neml/artifacts or /srv/neml/work")
    return resolved


def spec_checks(recipe: dict[str, Any], bbox: list[float]) -> list[dict[str, Any]]:
    """The measured overall sizes against the sizes the recipe promised (`spec`: [{axis, value, tol}])."""
    size = {"x": bbox[3] - bbox[0], "y": bbox[4] - bbox[1], "z": bbox[5] - bbox[2]}
    out = []
    for d in recipe.get("spec") or []:
        got = size[d["axis"]]
        tol = float(d.get("tol", 0.5))
        out.append({"axis": d["axis"], "wanted": d["value"], "measured": round(got, 3), "tol": tol, "ok": abs(got - d["value"]) <= tol})
    return out


async def build_recipe(recipe: dict[str, Any], out_dir: str, name: str, timeout_s: float = DEFAULT_TIMEOUT_S, process: str | None = None) -> dict[str, Any]:
    """Build a part from a declarative recipe in FreeCAD and export STL + STEP; nothing from the caller is executed.
    Measurements come back with it (area, thinnest wall, overhang area, threads, `spec` checks); `process` (print or cnc) adds manufacturing advice."""
    import re

    if not re.fullmatch(NAME_RE, name):
        raise CadError("name must be lowercase letters, digits and underscores")
    resolved = _under_roots(out_dir)
    recipe = repair_recipe(recipe)
    check_recipe(recipe)
    resolved.mkdir(parents=True, exist_ok=True)
    result = await _freecad(
        {
            "op": "csg", "solids": recipe["solids"], "steps": recipe.get("steps", []), "result": recipe["result"], "round": recipe.get("round"),
            "features": recipe.get("features") or [], "out_dir": str(resolved), "name": name,
        },
        min(timeout_s, 90.0),
    )
    if "error" in result:
        raise CadError(str(result["error"]))
    if "volume_mm3" not in result:
        raise CadError("recipe produced no solid")
    result = dict(result)
    if recipe.get("spec"):
        result["spec_checks"] = spec_checks(recipe, result["bbox"])
    if process:
        from . import dfm

        try:
            result["dfm"] = dfm.review(process, result, recipe)
        except ValueError as exc:
            raise CadError(str(exc)) from exc
    return result


async def convert(source: str, target: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """STEP/IGES -> STL for the 3D viewer (an imported part); paths stay under /srv/neml."""
    for p in (source, target):
        resolved = Path(p).resolve()
        if not any(
            root in resolved.parents
            for root in ALLOWED_ROOTS
        ):
            raise CadError("convert works only under /srv/neml/artifacts or /srv/neml/work")
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    result = await _freecad({"op": "convert", "source": source, "target": target}, timeout_s)
    if not Path(target).is_file():
        raise CadError("conversion wrote no STL")
    return dict(result)


async def drawing(
    step: str, out_dir: str, name: str, title: str = "", material: str = "", mass_g: float | None = None,
    tolerances: dict[str, str] | None = None, features: list[dict[str, Any]] | None = None, notes: list[str] | None = None,
    section: dict[str, Any] | None = None, scale: float | None = None, process: str = "", gdt: bool = False,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """A manufacturing drawing of a STEP part: three views in third-angle projection (hidden lines dashed), overall dimensions, hole callouts and position dimensions, surface roughness (Ra by `process`), optional position-tolerance frames (`gdt`), an optional
    section `{axis: x|y|z, at: mm}` with hatching, a title block and the standard scale. Written as <name>.svg and <name>.dxf."""
    import re

    from . import sheet

    if not re.fullmatch(NAME_RE, name):
        raise CadError("name must be lowercase letters, digits and underscores")
    src, resolved = _under_roots(step), _under_roots(out_dir)
    if section is not None and (not isinstance(section, dict) or section.get("axis") not in ("x", "y", "z")):
        raise CadError("section is {axis: x|y|z, at: mm}")
    if section is not None:
        _num(section.get("at"), -MAX_DIM_MM, MAX_DIM_MM, "section position")
    holes = []
    for f in features or []:
        if isinstance(f, dict) and f.get("f") == "hole":
            check_recipe({"solids": [{"id": "a", "t": "sphere", "r": 1, "at": [0, 0, 0]}], "result": "a", "features": [f]})
            holes.append(f)
    resolved.mkdir(parents=True, exist_ok=True)
    request: dict[str, Any] = {"op": "views", "source": str(src)}
    if section is not None:
        request["section"] = {"axis": section["axis"], "at": float(section["at"])}
    data = await _freecad(request, min(timeout_s, 90.0))
    if "error" in data:
        raise CadError(str(data["error"]))
    meta = {"title": title or name, "material": material, "mass_g": mass_g, "tolerances": tolerances or {}, "holes": holes, "notes": notes or [], "scale": scale, "process": process, "gdt": gdt}
    if section is not None:
        meta["section_label"] = f"{section['axis'].upper()}={section['at']:g}"
    svg, dxf, info = sheet.compose(data["views"], data["bbox"], meta)
    (resolved / f"{name}.svg").write_text(svg, encoding="utf-8")
    (resolved / f"{name}.dxf").write_text(dxf, encoding="ascii", errors="replace")
    return {"svg": str(resolved / f"{name}.svg"), "dxf": str(resolved / f"{name}.dxf"), **info, "bbox": data["bbox"]}


async def standard_part(kind: str, size: str, length: float = 0.0, out_dir: str = "/srv/neml/work/standard", name: str = "", timeout_s: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """A standard part built to its norm: screw (ISO 4762, size M3, length mm), nut (ISO 4032), washer (ISO 7089), bearing (size = designation, e.g. 608),
    profile (size 2020|3030|4040, length mm). Returns the norm name, mass and the built files."""
    from . import standards

    try:
        part = standards.standard_part(kind, size, length)
    except (KeyError, ValueError) as exc:
        raise CadError(f"no such standard part: {exc}") from exc
    label = name or f"{kind}_{size}_{int(length)}".lower().replace(".", "_")
    built = await build_recipe(part["recipe"], out_dir, label, timeout_s)
    return {"norm": part["norm"], "mass_g": part["mass_g"], "name": label, **built}


def fit(nominal: float, hole: str = "H7", shaft: str = "g6", timeout_s: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """ISO 286 limits and fit type of a hole/shaft pair, nominal 1..250 mm. Hole letters D E F G H JS, shaft letters d e f g h js k m n p, grades 5..12."""
    from . import standards

    try:
        return standards.fit(float(nominal), hole, shaft)
    except ValueError as exc:
        raise CadError(str(exc)) from exc


async def assemble(parts: list[dict[str, Any]], mates: list[dict[str, Any]], out_dir: str, name: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """Place parts by mates (stack, flush, align, offset, fixed; see assembly.py), then report interference (overlapping volume) and the gaps between parts that nearly touch.
    A part is `{id, recipe}` (built here) or `{id, step}` (a STEP under /srv/neml), with optional `rot` [rx, ry, rz] in multiples of 90."""
    import re

    from . import assembly

    if not re.fullmatch(NAME_RE, name):
        raise CadError("name must be lowercase letters, digits and underscores")
    resolved = _under_roots(out_dir)
    if not isinstance(parts, list) or not 2 <= len(parts) <= 40:
        raise CadError("an assembly has 2..40 parts")
    boxes: dict[str, dict[str, Any]] = {}
    files: dict[str, str] = {}
    volume: dict[str, float] = {}
    for p in parts:
        pid = p.get("id")
        if not isinstance(pid, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,23}", pid) or pid in boxes:
            raise CadError("every part needs a unique id (lowercase letters, digits, underscore)")
        rot = p.get("rot") or [0, 0, 0]
        if len(rot) != 3 or any(r not in (0, 90, 180, 270) for r in rot):
            raise CadError("rot is [rx, ry, rz], each 0, 90, 180 or 270")
        if p.get("recipe") is not None:
            built = await build_recipe(p["recipe"], str(resolved), f"{name}_{pid}", timeout_s)
            files[pid], boxes[pid], volume[pid] = built["step"], {"bbox": built["bbox"], "rot": rot}, built["volume_mm3"]
        elif p.get("step"):
            src = _under_roots(p["step"])
            views = await _freecad({"op": "views", "source": str(src)}, 90.0)
            if "error" in views:
                raise CadError(str(views["error"]))
            files[pid], boxes[pid], volume[pid] = str(src), {"bbox": views["bbox"], "rot": rot}, views["volume_mm3"]
        else:
            raise CadError(f"part {pid}: give a recipe or a step")
    try:
        placed = assembly.solve(boxes, mates or [])
    except (ValueError, KeyError, TypeError) as exc:
        raise CadError(f"mates: {exc}") from exc
    result = await _freecad(
        {"op": "assemble", "parts": [{"id": i, "step": files[i], "rot": placed[i]["rot"], "place": placed[i]["place"]} for i in files], "out_dir": str(resolved), "name": name},
        min(timeout_s, 110.0),
    )
    if "error" in result:
        raise CadError(str(result["error"]))
    return {**result, "placements": {i: {"place": placed[i]["place"], "rot": placed[i]["rot"]} for i in placed}, "ok": not result["interference"], "volumes_mm3": volume}


async def fem(step: str, material: str, fixed: str, load: dict[str, Any], mesh_mm: float = 0.0, out_dir: str = "/srv/neml/work/fem", timeout_s: float = 240.0) -> dict[str, Any]:
    """Static finite-element check of a STEP part: gmsh meshes it (second-order tetrahedra), the nodes on the `fixed` bounding-box side ('x-', 'z+', ...) are clamped
    and `load` = {face: 'x+', force: [fx, fy, fz] N} is spread over that side's surface. Returns the largest displacement, von Mises stress and the safety factor."""
    import asyncio

    from . import fem as solver

    src = _under_roots(step)
    work = _under_roots(out_dir)
    if material not in solver.MATERIAL:
        raise CadError(f"material must be one of {', '.join(solver.MATERIAL)}")
    if fixed not in SIDES or not isinstance(load, dict) or load.get("face") not in SIDES or fixed == load.get("face"):
        raise CadError("fixed and load.face are different sides: x+ x- y+ y- z+ z-")
    force = load.get("force")
    if not (isinstance(force, list) and len(force) == 3):
        raise CadError("load.force is [fx, fy, fz] in newtons")
    for v in force:
        _num(v, -1e6, 1e6, "force")
    work.mkdir(parents=True, exist_ok=True)
    msh = work / f"{src.stem}.msh"
    size = ["-clmax", str(mesh_mm)] if mesh_mm else ["-clmax", "5"]
    try:
        await _S.runner([os.getenv("GMSH_BIN", "gmsh"), str(src), "-3", "-order", "2", *size, "-format", "msh2", "-nopopup", "-o", str(msh)], timeout_s)
    except CliTimeout as exc:
        raise CadTimeoutError(str(exc)) from exc
    except Exception as exc:
        raise CadError(f"gmsh failed: {type(exc).__name__}: {exc}") from exc
    if not msh.is_file():
        raise CadError("gmsh wrote no mesh")

    def run() -> dict[str, Any]:
        nodes, tets, tris = solver.parse_msh(str(msh))
        if len(tets) > 20000:
            raise CadError(f"mesh has {len(tets)} elements; use a larger mesh_mm (this solver is meant for up to 20000)")
        return solver.solve(nodes, tets, tris, material, fixed, {"face": load["face"], "force": force})

    try:
        return await asyncio.to_thread(run)
    except ValueError as exc:
        raise CadError(str(exc)) from exc


TOOLS: dict[str, Callable[..., Any]] = {
    "convert": convert,
    "build_recipe": build_recipe,
    "drawing": drawing,
    "standard_part": standard_part,
    "fit": fit,
    "assemble": assemble,
    "fem": fem,
}

app = make_app("neml-mcp-cad", VERSION, TOOLS)

if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT)
