# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy. All rights reserved.
# Proprietary and confidential. Unauthorized use is prohibited.
"""Engineering layers of the CAD server that need no FreeCAD: ISO 286 fits, standard parts, mates, DFM, the drawing sheet and the FEM solver."""

from __future__ import annotations

import itertools

import pytest

from mcp_servers.neml_mcp_cad import assembly, dfm, server, sheet, standards

# --- ISO 286 -------------------------------------------------------------------------------------------------------------------------


def test_iso_286_fits_match_the_standard_tables() -> None:
    f = standards.fit(25, "H7", "g6")  # a classic sliding fit: 7..41 micrometres of clearance
    assert (f["clearance_min_mm"], f["clearance_max_mm"], f["type"]) == (0.007, 0.041, "boşluklu")
    assert standards.fit(10, "H7", "k6")["type"] == "geçişli"
    p = standards.fit(20, "H7", "p6")  # a press fit: always interference
    assert (p["clearance_min_mm"], p["clearance_max_mm"], p["type"]) == (-0.035, -0.001, "sıkı geçme")
    assert standards.limits(30, "JS9") == (-26.0, 26.0)  # 30 mm is in the 18..30 range: IT9 = 52
    for bad in ("Q7", "H99", "7H", "H"):
        with pytest.raises(ValueError):
            standards.limits(20, bad)
    with pytest.raises(ValueError):
        standards.limits(400, "H7")


def test_standard_parts_are_recipes_the_cad_server_accepts() -> None:
    for kind, size, length in (("screw", "M4", 12), ("nut", "M4", 0), ("washer", "M4", 0), ("bearing", "608", 0), ("profile", "2020", 100)):
        part = standards.standard_part(kind, size, length)
        server.check_recipe(part["recipe"])
        assert part["mass_g"] > 0 and part["norm"]
    with pytest.raises(ValueError):
        standards.standard_part("screw", "M4", 500)
    with pytest.raises(KeyError):
        standards.standard_part("bearing", "9999")


# --- mates ---------------------------------------------------------------------------------------------------------------------------


def test_mates_place_parts_by_constraints_not_coordinates() -> None:
    parts = {"base": {"bbox": [0, 0, 0, 60, 40, 10]}, "post": {"bbox": [0, 0, 0, 10, 10, 30]}, "cap": {"bbox": [0, 0, 0, 20, 20, 5], "rot": [0, 0, 90]}}
    got = assembly.solve(parts, [
        {"op": "stack", "a": "base", "b": "post", "axis": "z"},
        {"op": "offset", "a": "base", "b": "post", "d": [5, 5, 10]},
        {"op": "stack", "a": "post", "b": "cap", "axis": "z", "gap": 0.5},
    ])
    assert got["post"]["bbox"] == [5, 5, 10, 15, 15, 40]  # on the base, then moved by the offset
    assert got["cap"]["bbox"][2] == 40.5 and got["cap"]["bbox"][0] == 0  # half a millimetre above the post, turned a quarter, centred on it
    flush = assembly.solve({"a": {"bbox": [0, 0, 0, 10, 10, 10]}, "b": {"bbox": [0, 0, 0, 4, 4, 4]}}, [{"op": "flush", "a": "a", "b": "b", "axis": "x", "side": "max"}])
    assert flush["b"]["bbox"][3] == 10
    with pytest.raises(ValueError):
        assembly.solve({"a": {"bbox": [0, 0, 0, 1, 1, 1]}}, [{"op": "stack", "a": "a", "b": "ghost", "axis": "z"}])
    with pytest.raises(ValueError):
        assembly.solve({"a": {"bbox": [0, 0, 0, 1, 1, 1]}, "b": {"bbox": [0, 0, 0, 1, 1, 1]}}, [{"op": "weld", "a": "a", "b": "b"}])


def test_a_quarter_turn_swaps_the_box_sides() -> None:
    assert assembly.turned_box([0, 0, 0, 10, 20, 30], [0, 0, 90]) == [-20, 0, 0, 0, 10, 30]


# --- design for manufacture ----------------------------------------------------------------------------------------------------------


def test_dfm_flags_thin_walls_overhangs_and_small_holes_for_printing() -> None:
    info = {"min_wall_mm": 0.8, "bbox": [0, 0, 0, 260, 20, 10], "area_mm2": 1000, "overhang_mm2": 300}
    recipe = {"features": [{"f": "hole", "d": 1.5}, {"f": "hole", "kind": "tap", "d": 3}]}
    texts = " | ".join(f["text"] for f in dfm.review("print", info, recipe))
    for needle in ("1.2 mm", "sığmaz", "havada", "Ø1.5", "dişli burç"):
        assert needle in texts
    assert dfm.review("print", {"min_wall_mm": 2.0, "bbox": [0, 0, 0, 40, 30, 10], "area_mm2": 3000, "overhang_mm2": 0}, {}) == []
    cnc = dfm.review("cnc", {"min_wall_mm": 2, "bbox": [0, 0, 0, 40, 30, 10]}, {"solids": [{"id": "b", "t": "box"}], "steps": [{"op": "cut", "a": "a", "b": "b"}], "features": [{"f": "hole", "d": 3, "depth": 20}]})
    assert len(cnc) == 2 and {f["severity"] for f in cnc} == {"medium"}
    with pytest.raises(ValueError):
        dfm.review("forge", {}, {})


# --- drawing sheet -------------------------------------------------------------------------------------------------------------------


def _rect(x0: float, y0: float, x1: float, y1: float) -> list[list[float]]:
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


def test_the_sheet_scales_to_fit_and_places_the_views_without_overlap() -> None:
    views = {"front": {"visible": [_rect(0, 0, 60, 18)], "hidden": []}, "top": {"visible": [_rect(0, 0, 60, 30)], "hidden": [[[10, 5], [50, 5]]]}, "right": {"visible": [_rect(0, 0, 30, 18)], "hidden": []}}
    svg, dxf, info = sheet.compose(views, [0, 0, 0, 60, 30, 18], {"title": "Braket", "material": "PLA", "mass_g": 19, "tolerances": {"x": "±0.2"}, "holes": [{"at": [8, 8, 18], "axis": "z", "d": 3.4, "kind": "cbore", "d2": 6.5, "depth2": 3}], "gdt": True, "process": "print"})
    assert "Ra 12.5" in svg and ">8<" in svg and "Ø0.2" in svg  # roughness, hole position from the edges, position frame
    assert info == {"sheet": "A4", "scale": "1:1"} or info["sheet"] == "A4"
    assert "60 ±0.2" in svg and "Ø3.4" in svg and "PLA" in svg and "ISO 2768-m" in svg
    assert dxf.startswith("0\nSECTION") and dxf.rstrip().endswith("EOF") and "LINE" in dxf and "%%c" in dxf and "Ø" not in dxf
    # a bigger part moves to a bigger scale step or sheet, never off the paper
    big = {"front": {"visible": [_rect(0, 0, 500, 300)], "hidden": []}, "top": {"visible": [_rect(0, 0, 500, 400)], "hidden": []}, "right": {"visible": [_rect(0, 0, 400, 300)], "hidden": []}}
    _, _, info2 = sheet.compose(big, [0, 0, 0, 500, 400, 300], {"title": "Big"})
    w, h = sheet.SHEETS[info2["sheet"]]
    s = float(info2["scale"].split(":")[1]) if info2["scale"].startswith("1:") else 1 / float(info2["scale"].split(":")[0])
    assert (500 + 400) / s + sheet.PAD_L + sheet.PAD_R + sheet.GAP <= w - 20 + 1e-6 and (300 + 400) / s <= h
    assert sheet.scale_label(2) == "2:1" and sheet.scale_label(0.2) == "1:5"


# --- FEM -----------------------------------------------------------------------------------------------------------------------------

CORNERS = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)]
KUHN = [(0, 1, 3, 7), (0, 1, 5, 7), (0, 2, 3, 7), (0, 2, 6, 7), (0, 4, 5, 7), (0, 4, 6, 7)]  # a cube as six tetrahedra


def bar_mesh(nx: int, ny: int, nz: int, size: tuple[float, float, float]):
    """A box of second-order tetrahedra: nodes, tets (gmsh order) and the six-node triangles on the boundary."""
    import numpy as np


    coords: dict[tuple[float, float, float], int] = {}

    def node(p: tuple[float, float, float]) -> int:
        key = tuple(round(v, 9) for v in p)
        return coords.setdefault(key, len(coords))

    tets, faces = [], []
    sx, sy, sz = size[0] / nx, size[1] / ny, size[2] / nz
    for i, j, k in itertools.product(range(nx), range(ny), range(nz)):
        cube = [((i + a) * sx, (j + b) * sy, (k + c) * sz) for c in (0, 1) for b in (0, 1) for a in (0, 1)]
        for t in KUHN:
            v = [cube[n] for n in t]
            if np.linalg.det(np.array([np.subtract(v[q], v[0]) for q in (1, 2, 3)])) < 0:
                v[1], v[2] = v[2], v[1]  # outward orientation, as gmsh writes it
            mid = lambda a, b, v=v: tuple((v[a][q] + v[b][q]) / 2 for q in range(3))  # noqa: E731
            conn = [node(p) for p in v] + [node(mid(a, b)) for a, b in ((0, 1), (1, 2), (2, 0), (3, 0), (3, 2), (3, 1))]
            tets.append(conn)
            for tri, edges in (((0, 1, 2), (4, 5, 6)), ((0, 1, 3), (4, 9, 7)), ((1, 2, 3), (5, 8, 9)), ((0, 2, 3), (6, 8, 7))):
                faces.append([conn[n] for n in tri] + [conn[n] for n in edges])
    nodes = np.zeros((len(coords), 3))
    for p, n in coords.items():
        nodes[n] = p
    return nodes, np.array(tets), np.array(faces)


def test_fem_matches_a_pulled_bar_and_a_cantilever() -> None:
    pytest.importorskip("scipy")
    import numpy as np

    from mcp_servers.neml_mcp_cad import fem

    # patch test: a linear displacement field gives the uniform stress of Hooke's law on a distorted element
    nodes, tets, _ = bar_mesh(1, 1, 1, (2, 3, 5))
    d = fem.elasticity(3500, 0.36)
    eps = 0.001
    u = np.zeros(30)
    x = nodes[tets[0]]
    for n in range(10):
        u[3 * n] = eps * x[n][0]
    dn, det = fem.gradients(fem.shape_derivs(0.25, 0.25, 0.25), x)
    sigma = d @ fem.b_matrix(dn) @ u
    assert det > 0 and sigma[0] == pytest.approx(3500 * (1 - 0.36) / ((1.36) * (1 - 0.72)) * eps, rel=1e-6)
    assert sigma[1] == pytest.approx(sigma[2])

    # a bar clamped at x- and pulled at x+: the load comes back as stress F/A, and the length grows by about F L / (E A)
    length, w, h, force = 40.0, 4.0, 4.0, 100.0
    nodes, tets, tris = bar_mesh(8, 2, 2, (length, w, h))
    got = fem.solve(nodes, tets, tris, "PLA", "x-", {"face": "x+", "force": [force, 0, 0]})
    assert got["max_displacement_mm"] == pytest.approx(force * length / (3500 * w * h), rel=0.15)
    assert got["max_von_mises_mpa"] >= force / (w * h) * 0.9

    # a cantilever loaded at its tip: the tip drops by F L^3 / (3 E I) (second-order elements lock little)
    length, w, h, force = 60.0, 6.0, 6.0, 5.0
    nodes, tets, tris = bar_mesh(10, 2, 2, (length, w, h))
    got = fem.solve(nodes, tets, tris, "PLA", "x-", {"face": "x+", "force": [0, 0, -force]})
    analytic = force * length**3 / (3 * 3500 * (w * h**3 / 12))
    assert got["max_displacement_mm"] == pytest.approx(analytic, rel=0.15)


# --- the recipe language -------------------------------------------------------------------------------------------------------------

SKETCH = {"id": "p", "t": "prism", "plane": "xy", "at": [0, 0, 0], "h": 8, "pts": [[0, 0], [40, 0, 0.4], [40, 20], [0, 20]]}


def test_sketches_features_and_copies_are_valid_recipe_data() -> None:
    server.check_recipe({"solids": [SKETCH, {"id": "c", "t": "cyl", "r": 2, "h": 12, "axis": "z", "at": [5, 5, -2]},
                                    {"id": "cs", "t": "polar", "of": "c", "n": 4, "axis": "z", "at": [20, 10, 0]},
                                    {"id": "m", "t": "mirror", "of": "p", "plane": "yz", "at": [0, 0, 0]},
                                    {"id": "k", "t": "cone", "r": 5, "r2": 0, "h": 8, "axis": "z", "at": [0, 0, 0]},
                                    {"id": "t", "t": "pipe", "r": 3, "ri": 2, "path": [[0, 0, 0], [0, 0, 20], [20, 0, 20]], "at": [0, 0, 0]}],
                         "steps": [{"op": "cut", "a": "p", "b": "cs", "out": "r"}], "result": "r",
                         "features": [{"f": "hole", "kind": "cbore", "at": [10, 10, 8], "axis": "z", "dir": "-", "d": 3.4, "d2": 6.5, "depth2": 3}, {"f": "hole", "kind": "tap", "at": [30, 10, 8], "axis": "z", "dir": "-", "d": 4, "depth": 6}, {"f": "shell", "t": 1.6, "open": "z+"}],
                         "spec": [{"axis": "x", "value": 40, "tol": 0.2}]})
    base = {"solids": [SKETCH], "result": "p"}
    for bad in (
        {**base, "solids": [{**SKETCH, "plane": "ab"}]},
        {**base, "solids": [{**SKETCH, "pts": [[0, 0], [1, 1]]}]},  # a 2-point outline is only a circle of two arcs: it needs bulges, and a prism needs a height too
        {**base, "solids": [{**SKETCH, "pts": [[0, 0, 99], [4, 0], [4, 4]]}]},
        {**base, "solids": [{"id": "c", "t": "polar", "of": "ghost", "n": 4, "axis": "z", "at": [0, 0, 0]}]},
        {**base, "solids": [SKETCH, {"id": "a", "t": "array", "of": "p", "n": 99, "step": [1, 0, 0], "at": [0, 0, 0]}]},
        {**base, "solids": [{"id": "t", "t": "pipe", "r": 3, "path": [[0, 0, 0]], "at": [0, 0, 0]}], "result": "t"},
        {**base, "features": [{"f": "hole", "kind": "tap", "at": [1, 1, 1], "axis": "z", "dir": "-", "d": 3.3}]},  # M3.3 is not a metric size
        {**base, "features": [{"f": "hole", "kind": "cbore", "at": [1, 1, 1], "axis": "z", "dir": "-", "d": 5, "d2": 4, "depth2": 2}]},
        {**base, "features": [{"f": "weld"}]},
        {**base, "features": [{"f": "shell", "t": 1, "open": "up"}]},
        {**base, "spec": [{"axis": "w", "value": 4}]},
    ):
        if bad["solids"][0].get("pts") == [[0, 0], [1, 1]]:
            bad["solids"][0].pop("h")
        with pytest.raises(server.CadError):
            server.check_recipe(bad)


def test_a_copy_of_a_missing_solid_is_dropped_not_fatal() -> None:
    fixed = server.repair_recipe({"solids": [SKETCH, {"id": "c", "t": "array", "of": "ghost", "n": 2, "step": [1, 0, 0], "at": [0, 0, 0]}], "steps": [{"op": "cut", "a": "p", "b": "c", "out": "r"}], "result": "r"})
    server.check_recipe(fixed)
    assert [s["id"] for s in fixed["solids"]] == ["p"] and fixed["steps"] == []


def test_spec_checks_report_measured_against_promised_sizes() -> None:
    got = server.spec_checks({"spec": [{"axis": "x", "value": 40, "tol": 0.2}, {"axis": "z", "value": 10}]}, [0, 0, 0, 40.1, 20, 12])
    assert [c["ok"] for c in got] == [True, False] and got[1]["measured"] == 12
