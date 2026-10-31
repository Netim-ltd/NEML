# ruff: noqa
# Copyright (c) 2026 Mustafa Gulsoy. All rights reserved.
# Proprietary and confidential. Unauthorized use is prohibited.
"""Runs *inside* freecadcmd (the only interpreter that can import FreeCAD); the server hands it a validated request file.

ops: convert (STEP/IGES -> STL), csg (a recipe -> solid, measured, exported), views (orthographic line work of a STEP), assemble (placed parts, interference).
Nothing from the request is executed: it is read as data."""
import json, math, sys

request = json.load(open(sys.argv[-1]))
OP = request["op"]


def done(data):
    json.dump(data, open(request["result_path"], "w"))
    sys.exit(0)


def fail(message):
    done({"error": str(message)})


import FreeCAD as App
import Part

V = App.Vector
AXES = {"x": V(1, 0, 0), "y": V(0, 1, 0), "z": V(0, 0, 1)}
# profile plane -> (local (u, v) to a 3D point from the origin, extrusion normal)
PLANES = {
    "xy": (lambda u, v, o: V(o.x + u, o.y + v, o.z), V(0, 0, 1)),
    "xz": (lambda u, v, o: V(o.x + u, o.y, o.z + v), V(0, 1, 0)),
    "yz": (lambda u, v, o: V(o.x, o.y + u, o.z + v), V(1, 0, 0)),
}
TAP_DRILL = {2: 1.6, 2.5: 2.05, 3: 2.5, 4: 3.3, 5: 4.2, 6: 5.0, 8: 6.8, 10: 8.5, 12: 10.2}


def vec(a, k=1.0):
    return V(a.x * k, a.y * k, a.z * k)


def profile_wire(pts, plane, origin):
    """A closed wire from [u, v] or [u, v, bulge] points (bulge = tan(angle/4), positive = counter-clockwise arc to the next point)."""
    mk = PLANES[plane][0]
    edges = []
    for i, p in enumerate(pts):
        q = pts[(i + 1) % len(pts)]
        a, b = mk(p[0], p[1], origin), mk(q[0], q[1], origin)
        bulge = p[2] if len(p) > 2 else 0.0
        if a.distanceToPoint(b) < 1e-9:
            continue
        if abs(bulge) < 1e-9:
            edges.append(Part.makeLine(a, b))
        else:
            dx, dy = q[0] - p[0], q[1] - p[1]
            c = math.hypot(dx, dy)
            s = c / 2 * bulge
            mid = mk((p[0] + q[0]) / 2 + dy / c * s, (p[1] + q[1]) / 2 - dx / c * s, origin)
            edges.append(Part.Arc(a, mid, b).toShape())
    return Part.Wire(edges)


def circle_wire(r, plane, origin):
    return Part.Wire(Part.makeCircle(r, origin, PLANES[plane][1]))


def make_solid(s, solids):
    x, y, z = s["at"]
    at = V(x, y, z)
    t = s["t"]
    if t == "box":
        return Part.makeBox(s["size"][0], s["size"][1], s["size"][2], at)
    if t == "cyl":
        return Part.makeCylinder(s["r"], s["h"], at, AXES[s["axis"]])
    if t == "sphere":
        return Part.makeSphere(s["r"], at)
    if t == "cone":
        return Part.makeCone(s["r"], s["r2"], s["h"], at, AXES[s["axis"]])
    if t in ("prism", "turn", "loft"):
        plane = s.get("plane", "xy")
        w = profile_wire(s["pts"], plane, at) if s.get("pts") else circle_wire(s["r"], plane, at)
        face = Part.Face(w)
        if t == "prism":
            return face.extrude(vec(PLANES[plane][1], s["h"]))
        if t == "turn":
            mk = PLANES[plane][0]
            zero = V(0, 0, 0)
            d = mk(1, 0, zero) if s.get("about", "v") == "u" else mk(0, 1, zero)
            return face.revolve(at, d, s.get("angle", 360))
        top = at + vec(PLANES[plane][1], s["h"])
        w2 = profile_wire(s["pts2"], plane, top)
        return Part.makeLoft([w, w2], True)
    if t == "pipe":
        path = [V(*p) for p in s["path"]]

        def tube(r):  # straight runs joined by balls at the corners (a swept pipe breaks on sharp corners)
            parts = [Part.makeSphere(r, p) for p in path[1:-1]]
            for p, q in zip(path, path[1:]):
                d = q - p
                if d.Length > 1e-6:
                    parts.append(Part.makeCylinder(r, d.Length, p, d))
            return parts[0].multiFuse(parts[1:]) if len(parts) > 1 else parts[0]

        body = tube(s["r"])
        if s.get("ri"):
            body = body.cut(tube(s["ri"]))
        return body
    base = solids[s["of"]]
    if t == "array":
        step = V(*s["step"])
        copies = []
        for i in range(s["n"]):
            c = base.copy()
            c.translate(vec(step, i))
            copies.append(c)
        return copies[0].multiFuse(copies[1:]) if len(copies) > 1 else copies[0]
    if t == "polar":
        n, ang = s["n"], s.get("angle", 360)
        each = ang / n if ang >= 360 else ang / max(n - 1, 1)
        copies = []
        for i in range(n):
            c = base.copy()
            c.rotate(at, AXES[s["axis"]], each * i)
            copies.append(c)
        return copies[0].multiFuse(copies[1:]) if len(copies) > 1 else copies[0]
    if t == "mirror":
        return base.mirror(at, PLANES[s["plane"]][1])
    raise ValueError("unknown solid type %s" % t)


def side_face(shape, side):
    """The planar face furthest out toward 'x+', 'z-', ..."""
    ax, sgn = "xyz".index(side[0]), 1 if side[1] == "+" else -1
    best, best_pos = None, None
    for fc in shape.Faces:
        if fc.Surface.__class__.__name__ != "Plane":
            continue
        u0, u1, v0, v1 = fc.ParameterRange
        n = fc.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
        if [n.x, n.y, n.z][ax] * sgn < 0.99:
            continue
        c = fc.CenterOfMass
        pos = [c.x, c.y, c.z][ax] * sgn
        if best is None or pos > best_pos:
            best, best_pos = fc, pos
    return best


def drill(shape, f, notes):
    bb = shape.BoundBox
    big = 2 * max(bb.XLength, bb.YLength, bb.ZLength) + 10
    sign = 1 if f.get("dir", "-") == "+" else -1
    d = vec(AXES[f["axis"]], sign)
    start = V(*f["at"]) - vec(d, 0.5)
    depth = (f.get("depth") or big) + 0.5
    dia, kind = f["d"], f.get("kind", "plain")
    if kind == "tap":
        nominal = dia
        dia = TAP_DRILL.get(nominal, round(nominal * 0.85, 2))
        notes.append({"thread": "M%g" % nominal, "drill": dia, "depth": f.get("depth") or None, "at": f["at"], "axis": f["axis"]})
    parts = [Part.makeCylinder(dia / 2, depth, start, d)]
    if kind == "cbore":
        parts.append(Part.makeCylinder(f["d2"] / 2, f["depth2"] + 0.5, start, d))
    elif kind == "csink":
        cone_h = (f["d2"] - dia) / 2
        parts.append(Part.makeCone(f["d2"] / 2 + 0.5, dia / 2, cone_h + 0.5, start, d))
    cutter = parts[0]
    for p in parts[1:]:
        cutter = cutter.fuse(p)
    return shape.cut(cutter)


def apply_features(shape, features, notes):
    for f in features or []:
        if f["f"] == "hole":
            shape = drill(shape, f, notes)
        elif f["f"] == "shell":
            face = side_face(shape, f["open"])
            if face is None:
                raise ValueError("shell: no flat face on side %s" % f["open"])
            try:
                shape = shape.makeThickness([face], -f["t"], 1e-3)
            except Exception:
                raise ValueError("shell t=%s does not fit this solid: use a thinner wall" % f["t"])
    return shape


def rounding(shape, rd):
    zmax, zmin = shape.BoundBox.ZMax, shape.BoundBox.ZMin

    def wanted(e):
        a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
        if rd["edges"] == "vertical":
            return abs(a.x - b.x) < 1e-6 and abs(a.y - b.y) < 1e-6 and abs(a.z - b.z) > 1e-6
        if rd["edges"] in ("top", "bottom"):
            z = zmax if rd["edges"] == "top" else zmin
            return abs(a.z - z) < 1e-6 and abs(b.z - z) < 1e-6
        return True

    picked = [e for e in shape.Edges if wanted(e)]
    if not picked:
        raise ValueError("round: no %s edges on this solid" % rd["edges"])
    try:
        return shape.makeFillet(rd["r"], picked) if rd["kind"] == "fillet" else shape.makeChamfer(rd["r"], picked)
    except Exception:
        raise ValueError("round r=%s does not fit these %s edges: use a smaller r or other edges" % (rd["r"], rd["edges"]))


def measure(shape):
    """Numbers the judges use: surface area, thinnest wall (rays through the material from sampled faces) and the area that overhangs when printed upright."""
    bb = shape.BoundBox
    out = {"area_mm2": shape.Area}
    reach = max(bb.XLength, bb.YLength, bb.ZLength) + 1
    thin = None
    over = 0.0
    taken = 0
    for fc in shape.Faces:
        try:
            u0, u1, v0, v1 = fc.ParameterRange
            planar = fc.Surface.__class__.__name__ == "Plane"
            if planar:
                n0 = fc.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
                if n0.z < -0.7071 and fc.BoundBox.ZMax > bb.ZMin + 0.01:
                    over += fc.Area
            if taken >= 120:
                continue
            for fu, fv in ((0.5, 0.5), (0.25, 0.25), (0.75, 0.75), (0.25, 0.75), (0.75, 0.25)):
                u, v = u0 + (u1 - u0) * fu, v0 + (v1 - v0) * fv
                p = fc.valueAt(u, v)
                if not fc.isInside(p, 1e-6, True):
                    continue
                n = fc.normalAt(u, v)
                line = Part.makeLine(p - vec(n, 0.001), p - vec(n, reach))
                taken += 1
                inside = line.common(shape).Edges
                if inside:
                    length = min(inside, key=lambda e: e.distToShape(Part.Vertex(p))[0]).Length
                    thin = length if thin is None else min(thin, length)
                if not planar:
                    break
        except Exception:
            continue
    out["min_wall_mm"] = None if thin is None else round(thin, 3)
    out["overhang_mm2"] = round(over, 2)
    return out


def mesh_to(shape, path, lin, ang):
    try:
        import MeshPart
        MeshPart.meshFromShape(Shape=shape, LinearDeflection=lin, AngularDeflection=ang).write(path)
        return True
    except Exception:
        return False


try:
    if OP == "convert":
        shape = Part.read(request["source"])
        shape.exportStl(request["target"])
        bb = shape.BoundBox
        done({"volume_mm3": shape.Volume, "bbox": [bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax]})

    if OP == "csg":
        solids = {}
        for s in request["solids"]:
            solids[s["id"]] = make_solid(s, solids)
        for st in request["steps"]:
            a, b = solids[st["a"]], solids[st["b"]]
            solids[st["out"]] = a.cut(b) if st["op"] == "cut" else a.fuse(b)
        shape = solids[request["result"]].removeSplitter()
        notes = []
        shape = apply_features(shape, request.get("features"), notes)
        if request.get("round"):
            shape = rounding(shape, request["round"])
        if not shape.isValid() or shape.Volume <= 0:
            raise ValueError("result is not a valid solid")
        if len(shape.Solids) != 1:
            raise ValueError("result is %d separate solids: fuse the pieces so they touch or overlap" % len(shape.Solids))
        out = request["out_dir"] + "/" + request["name"]
        obj = App.newDocument("g").addObject("Part::Feature", "g")
        obj.Shape = shape
        Part.export([obj], out + ".step")
        if not mesh_to(shape, out + ".stl", 0.2, 0.5):  # a coarser mesh than exportStl's default: round parts came out at 190k triangles (9 MB), over the media store's 8 MB
            shape.exportStl(out + ".stl")
        files = {"stl": out + ".stl", "step": out + ".step"}
        if mesh_to(shape, out + ".3mf", 0.1, 0.3):  # 3MF for slicers; the mesh module is optional in a headless build
            files["threemf"] = out + ".3mf"
        bb = shape.BoundBox
        result = {"volume_mm3": shape.Volume, "bbox": [bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax],
                  "center_of_mass": list(shape.Solids[0].CenterOfMass), "threads": notes, **files}
        try:
            result.update(measure(shape))
        except Exception:
            pass
        done(result)

    if OP == "views":
        import TechDraw
        shape = Part.read(request["source"])
        bases = {  # u right, v up, w toward the viewer (third-angle projection)
            "front": ((1, 0, 0), (0, 0, 1), (0, -1, 0)),
            "top": ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
            "right": ((0, 1, 0), (0, 0, 1), (1, 0, 0)),
        }

        def turned(sh, name):
            u, v, w = bases[name]
            m = App.Matrix(u[0], u[1], u[2], 0, v[0], v[1], v[2], 0, w[0], w[1], w[2], 0, 0, 0, 0, 1)
            return sh.transformGeometry(m)

        def lines(compound):
            polys = []
            for e in compound.Edges:
                pts = e.discretize(Deflection=0.05) if e.Length > 0 else []
                if len(pts) >= 2:
                    polys.append([[round(p.x, 4), round(p.y, 4)] for p in pts])
            return polys

        def view(sh, name):
            t = turned(sh, name)
            res = TechDraw.projectEx(t, V(0, 0, 1))  # 0 sharp, 1 smooth, 3 outline (visible); 5, 6, 8 the same, hidden
            return {"visible": lines(res[0]) + lines(res[1]) + lines(res[3]), "hidden": lines(res[5]) + lines(res[6]) + lines(res[8])}

        out = {name: view(shape, name) for name in ("front", "top", "right")}
        sec = request.get("section")
        if sec:
            ax, at = sec["axis"], sec["at"]
            bb = shape.BoundBox
            big = 4 * max(bb.XLength, bb.YLength, bb.ZLength) + 100
            # the half removed: y < at (front basis), x > at (right basis), z > at (top basis)
            if ax == "y":
                tool = Part.makeBox(big, big, big, V(bb.XMin - big / 2, at - big, bb.ZMin - big / 2))
                name = "front"
            elif ax == "x":
                tool = Part.makeBox(big, big, big, V(at, bb.YMin - big / 2, bb.ZMin - big / 2))
                name = "right"
            else:
                tool = Part.makeBox(big, big, big, V(bb.XMin - big / 2, bb.YMin - big / 2, at))
                name = "top"
            kept = shape.cut(tool)
            sv = view(kept, name)
            rings = []
            for fc in kept.Faces:
                if fc.Surface.__class__.__name__ != "Plane":
                    continue
                c = fc.BoundBox
                lo_, hi_ = {"x": (c.XMin, c.XMax), "y": (c.YMin, c.YMax), "z": (c.ZMin, c.ZMax)}[ax]
                if hi_ - lo_ > 1e-4 or abs(lo_ - at) > 1e-4:
                    continue
                for w in fc.Wires:  # a wire is walked in order, so the ring closes on itself (edges of a compound come in any order)
                    bu, bv, _ = bases[name]
                    pts = [[round(bu[0] * p.x + bu[1] * p.y + bu[2] * p.z, 4), round(bv[0] * p.x + bv[1] * p.y + bv[2] * p.z, 4)] for p in w.discretize(Deflection=0.05)]
                    if len(pts) >= 3:
                        rings.append(pts)
            sv["hatch"] = rings
            sv["basis"] = name
            out["section"] = sv
        bb = shape.BoundBox
        done({"views": out, "bbox": [bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax], "volume_mm3": shape.Volume})

    if OP == "assemble":
        placed = {}
        for p in request["parts"]:
            sh = Part.read(p["step"])
            for ax, ang in zip("xyz", p.get("rot", [0, 0, 0])):
                if ang:
                    sh.rotate(V(0, 0, 0), AXES[ax], ang)
            sh.translate(V(*p["place"]))
            placed[p["id"]] = sh
        ids = list(placed)
        clashes, near = [], []
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = placed[ids[i]], placed[ids[j]]
                if not a.BoundBox.intersect(b.BoundBox):
                    continue
                try:
                    vol = a.common(b).Volume
                except Exception:
                    vol = 0.0
                if vol > 0.5:
                    clashes.append({"a": ids[i], "b": ids[j], "volume_mm3": round(vol, 2)})
                else:
                    near.append({"a": ids[i], "b": ids[j], "gap_mm": round(a.distToShape(b)[0], 3)})
        comp = Part.makeCompound(list(placed.values()))
        out = request["out_dir"] + "/" + request["name"]
        obj = App.newDocument("a").addObject("Part::Feature", "a")
        obj.Shape = comp
        Part.export([obj], out + ".step")
        if not mesh_to(comp, out + ".stl", 0.3, 0.6):
            comp.exportStl(out + ".stl")
        bb = comp.BoundBox
        done({"parts": {i: [placed[i].BoundBox.XMin, placed[i].BoundBox.YMin, placed[i].BoundBox.ZMin, placed[i].BoundBox.XMax, placed[i].BoundBox.YMax, placed[i].BoundBox.ZMax] for i in ids},
              "interference": clashes, "contacts": near, "bbox": [bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax],
              "volume_mm3": sum(p.Volume for p in placed.values()), "step": out + ".step", "stl": out + ".stl"})

    fail("unknown op %s" % OP)
except SystemExit:
    raise
except Exception as exc:
    fail(exc)
