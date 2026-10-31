# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Mesh files from other people's repositories, read as numbers and written as binary STL.

Collada (.dae, what ROS robots mostly ship) and PLY are parsed here; OBJ and STL live in imports.py.
Nothing is executed: Collada is XML read without DTD/entities, with its asset unit and up axis
applied (the result is in metres, Z up, the way ROS loaders show it), PLY is a header plus numbers.
The result is a triangle array that `write_stl` turns into the binary STL the rest of the pipeline
(bounds, viewer, STL export) already understands.
"""

from __future__ import annotations

import struct
import xml.etree.ElementTree as ET  # noqa: S405 - DTD/entities are refused before parsing
from pathlib import Path

import numpy as np

MAX_TRIANGLES = 800_000
MAX_BYTES = 60 * 1024 * 1024


class MeshError(ValueError):
    """The file is not a mesh this module can read safely."""


def write_stl(triangles: np.ndarray, target: Path) -> Path:
    """Binary STL of an (n, 3, 3) triangle array; degenerate triangles get a +z normal."""
    n = len(triangles)
    if n == 0:
        raise MeshError("no triangles")
    if n > MAX_TRIANGLES:
        raise MeshError(f"{n} triangles (at most {MAX_TRIANGLES})")
    tri = np.asarray(triangles, dtype="<f4")
    normal = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    length = np.linalg.norm(normal, axis=1, keepdims=True)
    normal = np.where(length > 0, normal / np.where(length > 0, length, 1), np.array([0, 0, 1.0]))
    record = np.zeros(n, dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    record["n"], record["v"] = normal, tri
    target.write_bytes(bytes(80) + struct.pack("<I", n) + record.tobytes())
    return target


# ---------------------------------------------------------------------- Collada
def strip(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def children(el: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in el if strip(c.tag) == name]


def child(el: ET.Element, name: str) -> ET.Element | None:
    found = children(el, name)
    return found[0] if found else None


def floats(el: ET.Element | None) -> np.ndarray:
    return np.array((el.text or "").split(), dtype=float) if el is not None else np.array([])


def node_matrix(node: ET.Element) -> np.ndarray:
    """The transform a Collada node applies: matrix, translate, rotate, scale in document order."""
    m = np.eye(4)
    for op in node:
        kind = strip(op.tag)
        v = floats(op)
        t = np.eye(4)
        if kind == "matrix" and len(v) == 16:
            t = v.reshape(4, 4)
        elif kind == "translate" and len(v) == 3:
            t[:3, 3] = v
        elif kind == "scale" and len(v) == 3:
            t[0, 0], t[1, 1], t[2, 2] = v
        elif kind == "rotate" and len(v) == 4:
            axis = v[:3] / (np.linalg.norm(v[:3]) or 1.0)
            a = np.radians(v[3])
            c, s, (x, y, z) = np.cos(a), np.sin(a), axis
            t[:3, :3] = [
                [c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
                [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
                [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)],
            ]
        else:
            continue
        m = m @ t
    return m


def geometry_triangles(geometry: ET.Element) -> np.ndarray:
    """All triangles of a <geometry><mesh>: triangles, polylist and polygons, polygons fanned."""
    mesh = child(geometry, "mesh")
    if mesh is None:
        return np.zeros((0, 3, 3))
    sources: dict[str, np.ndarray] = {}
    for src in children(mesh, "source"):
        array = child(src, "float_array")
        common = child(src, "technique_common")
        accessor = child(common if common is not None else src, "accessor")
        stride = int(accessor.get("stride", "3")) if accessor is not None else 3
        if array is not None and src.get("id"):
            values = floats(array)
            sources[str(src.get("id"))] = values[: len(values) // stride * stride].reshape(
                -1, stride
            )
    vertex_source: dict[str, str] = {}
    for vertices in children(mesh, "vertices"):
        for inp in children(vertices, "input"):
            if inp.get("semantic") == "POSITION":
                vertex_source[str(vertices.get("id"))] = str(inp.get("source", "")).lstrip("#")
    out: list[np.ndarray] = []
    for kind in ("triangles", "polylist", "polygons"):
        for prim in children(mesh, kind):
            inputs = children(prim, "input")
            vertex_input = next((i for i in inputs if i.get("semantic") == "VERTEX"), None)
            if vertex_input is None:
                continue
            offset = int(vertex_input.get("offset", "0"))
            stride = max(int(i.get("offset", "0")) for i in inputs) + 1
            ref = str(vertex_input.get("source", "")).lstrip("#")
            positions = sources.get(vertex_source.get(ref, ref))
            if positions is None or positions.shape[1] < 3:
                continue
            if kind == "triangles":
                p = np.array((child(prim, "p").text or "").split(), dtype=int)  # type: ignore[union-attr]
                idx = p[: len(p) // stride * stride].reshape(-1, stride)[:, offset].reshape(-1, 3)
                out.append(positions[idx][:, :, :3])
            else:
                counts = (
                    np.array((child(prim, "vcount").text or "").split(), dtype=int)  # type: ignore[union-attr]
                    if kind == "polylist"
                    else np.array(
                        [len((p.text or "").split()) // stride for p in children(prim, "p")]
                    )
                )
                flat = (
                    " ".join(p.text or "" for p in children(prim, "p"))
                    if kind == "polygons"
                    else (child(prim, "p").text or "")  # type: ignore[union-attr]
                )
                data = np.array(flat.split(), dtype=int)
                data = data[: len(data) // stride * stride].reshape(-1, stride)[:, offset]
                cursor = 0
                fans: list[tuple[int, int, int]] = []
                for n in counts:
                    ring = data[cursor : cursor + n]
                    cursor += n
                    fans += [(ring[0], ring[k], ring[k + 1]) for k in range(1, n - 1)]
                if fans:
                    out.append(positions[np.array(fans)][:, :, :3])
            if sum(len(a) for a in out) > MAX_TRIANGLES:
                raise MeshError("too many triangles")
    return np.concatenate(out) if out else np.zeros((0, 3, 3))


def dae_triangles(path: Path) -> np.ndarray:
    """Every triangle of a Collada file placed by its visual scene, in metres, Z up."""
    if path.stat().st_size > MAX_BYTES:
        raise MeshError("file is too large")
    data = path.read_bytes()
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise MeshError("DTD/entity declarations are refused")
    try:
        root = ET.fromstring(data)  # noqa: S314 - DTD/entities refused above
    except ET.ParseError as exc:
        raise MeshError(f"not valid XML ({exc})") from exc
    if strip(root.tag) != "COLLADA":
        raise MeshError("not a Collada file")
    asset = child(root, "asset")
    unit = child(asset, "unit") if asset is not None else None
    meters = float(unit.get("meter", "1")) if unit is not None else 1.0
    up_el = child(asset, "up_axis") if asset is not None else None
    up = (up_el.text or "Z_UP").strip() if up_el is not None else "Z_UP"
    if up == "X_UP":
        raise MeshError("X_UP files are not supported")
    geometries = {
        str(g.get("id")): g
        for lib in children(root, "library_geometries")
        for g in children(lib, "geometry")
    }
    placed: list[np.ndarray] = []

    def visit(node: ET.Element, parent: np.ndarray, depth: int = 0) -> None:
        if depth > 32:
            raise MeshError("scene graph is too deep")
        m = parent @ node_matrix(node)
        for inst in children(node, "instance_geometry"):
            geometry = geometries.get(str(inst.get("url", "")).lstrip("#"))
            if geometry is not None:
                tri = geometry_triangles(geometry)
                if len(tri):
                    homogeneous = np.concatenate([tri, np.ones((*tri.shape[:2], 1))], axis=2)
                    placed.append((homogeneous @ m.T)[:, :, :3])
        for sub in children(node, "node"):
            visit(sub, m, depth + 1)

    scenes = [
        s for lib in children(root, "library_visual_scenes") for s in children(lib, "visual_scene")
    ]
    if scenes:
        for node in children(scenes[0], "node"):
            visit(node, np.eye(4))
    if not placed:  # no scene graph: the geometries as they are
        placed = [t for t in (geometry_triangles(g) for g in geometries.values()) if len(t)]
    if not placed:
        raise MeshError("no triangles in the file")
    tri = np.concatenate(placed) * meters
    if up == "Y_UP":
        tri = np.stack([tri[:, :, 0], -tri[:, :, 2], tri[:, :, 1]], axis=2)
    return tri


def dae_to_stl(path: Path) -> Path:
    return write_stl(dae_triangles(path), path.with_suffix(".conv.stl"))


# -------------------------------------------------------------------------- PLY
PLY_TYPES = {
    "char": "i1", "uchar": "u1", "int8": "i1", "uint8": "u1", "short": "i2", "ushort": "u2",
    "int16": "i2", "uint16": "u2", "int": "i4", "uint": "u4", "int32": "i4", "uint32": "u4",
    "float": "f4", "float32": "f4", "double": "f8", "float64": "f8",
}  # fmt: skip


def ply_triangles(path: Path) -> np.ndarray:
    """Vertices and faces of an ASCII or binary little-endian PLY, faces fanned into triangles."""
    if path.stat().st_size > MAX_BYTES:
        raise MeshError("file is too large")
    raw = path.read_bytes()
    end = raw.find(b"end_header")
    if not raw.startswith(b"ply") or end < 0:
        raise MeshError("not a PLY file")
    header = raw[:end].decode("ascii", errors="replace").splitlines()
    body = raw[raw.index(b"\n", end) + 1 :]
    fmt = next((ln.split()[1] for ln in header if ln.startswith("format")), "")
    if fmt not in ("ascii", "binary_little_endian"):
        raise MeshError(f"PLY format '{fmt}' is not supported")
    elements: list[tuple[str, int, list[list[str]]]] = []
    for line in header:
        words = line.split()
        if words[:1] == ["element"]:
            elements.append((words[1], int(words[2]), []))
        elif words[:1] == ["property"] and elements:
            elements[-1][2].append(words[1:])
    vertices: np.ndarray | None = None
    faces: list[list[int]] | None = None
    if fmt == "ascii":
        tokens = body.decode("ascii", errors="replace").split()
        cursor = 0
        for name, count, props in elements:
            if name == "vertex":
                width = len(props)
                block = np.array(tokens[cursor : cursor + count * width], dtype=float).reshape(
                    count, width
                )
                names = [p[-1] for p in props]
                vertices = block[:, [names.index("x"), names.index("y"), names.index("z")]]
                cursor += count * width
            elif name == "face":
                rows: list[list[int]] = []
                for _ in range(count):
                    n = int(tokens[cursor])
                    rows.append([int(t) for t in tokens[cursor + 1 : cursor + 1 + n]])
                    cursor += 1 + n + sum(1 for p in props[1:])  # extra scalar properties
                faces = rows
            else:
                cursor += count * len(props)
    else:
        offset = 0
        for name, count, props in elements:
            if name == "vertex":
                dtype = np.dtype([(p[-1], "<" + PLY_TYPES[p[0]]) for p in props])
                records = np.frombuffer(body, dtype=dtype, count=count, offset=offset)
                vertices = np.stack([records["x"], records["y"], records["z"]], axis=1).astype(
                    float
                )
                offset += dtype.itemsize * count
            elif name == "face":
                list_prop = next(p for p in props if p[0] == "list")
                count_type, index_type = (
                    "<" + PLY_TYPES[list_prop[1]],
                    "<" + PLY_TYPES[list_prop[2]],
                )
                rows = []
                for _ in range(count):
                    n = int(np.frombuffer(body, dtype=count_type, count=1, offset=offset)[0])
                    offset += np.dtype(count_type).itemsize
                    rows.append(
                        np.frombuffer(body, dtype=index_type, count=n, offset=offset).tolist()
                    )
                    offset += np.dtype(index_type).itemsize * n
                faces = rows
            else:
                raise MeshError(f"PLY element '{name}' before the faces is not supported")
    if vertices is None or not faces:
        raise MeshError("PLY has no vertices or faces")
    fans = [(f[0], f[k], f[k + 1]) for f in faces for k in range(1, len(f) - 1)]
    if not fans or max(max(t) for t in fans) >= len(vertices):
        raise MeshError("PLY faces point outside the vertices")
    return np.asarray(vertices[np.array(fans)])


def ply_to_stl(path: Path) -> Path:
    return write_stl(ply_triangles(path), path.with_suffix(".conv.stl"))


# ----------------------------------------------------------- compact viewer mesh
def compact(triangles: np.ndarray) -> bytes:
    """The viewer's own small format (.nmesh): welded vertices on a 16-bit grid, indexed triangles.

    NM1, vertex count, index count, box min (3 floats), box max (3 floats), then the vertices as
    uint16 x y z and the indices as uint16 (uint32 above 65535 vertices). A 1 MB STL becomes about
    a fifth of that, the position error is the box size / 65535.
    """
    flat = np.asarray(triangles, dtype=np.float64).reshape(-1, 3)
    lo, hi = flat.min(axis=0), flat.max(axis=0)
    span = np.where(hi > lo, hi - lo, 1.0)
    grid = np.rint((flat - lo) / span * 65535).astype(np.uint16)
    unique, inverse = np.unique(grid, axis=0, return_inverse=True)
    index_type = "<u2" if len(unique) < 65536 else "<u4"
    header = b"NM1\0" + struct.pack("<II3f3f", len(unique), len(inverse), *lo, *hi)
    return (
        header + unique.astype("<u2").tobytes() + inverse.astype(index_type).reshape(-1).tobytes()
    )


def expand(data: bytes) -> np.ndarray:
    """Inverse of `compact` (tests and tools): the (n, 3, 3) triangles back."""
    if data[:4] != b"NM1\0":
        raise MeshError("not an nmesh")
    vertex_count, index_count = struct.unpack_from("<II", data, 4)
    lo = np.array(struct.unpack_from("<3f", data, 12))
    hi = np.array(struct.unpack_from("<3f", data, 24))
    pos = 36
    vertices = np.frombuffer(data, dtype="<u2", count=vertex_count * 3, offset=pos).reshape(-1, 3)
    pos += vertex_count * 6
    index_type = "<u2" if vertex_count < 65536 else "<u4"
    indices = np.frombuffer(data, dtype=index_type, count=index_count, offset=pos)
    span = np.where(hi > lo, hi - lo, 1.0)
    return np.asarray((lo + vertices.astype(float) / 65535 * span)[indices].reshape(-1, 3, 3))


def stl_triangles(path: Path) -> np.ndarray:
    """Triangles of a binary STL file."""
    raw = path.read_bytes()
    count = struct.unpack("<I", raw[80:84])[0]
    record = np.frombuffer(
        raw[84:], dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]), count=count
    )
    return np.asarray(record["v"], dtype=float)
