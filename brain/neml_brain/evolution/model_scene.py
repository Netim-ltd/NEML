# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The 3D scene of a robot model: what the panel's viewer draws and animates.

The parts are what the lab's model designed through the CAD MCP (real FreeCAD solids) or what was
imported; bought parts are boxes of the real size. All are placed by the model's own URDF.

Units are millimetres, +x forward, +y left, +z up, the origin at the body centre. A part's
`explode` vector is where it flies to in the exploded view.
"""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from neml_brain.evolution.import_layout import place, rig_of_imports
from neml_brain.paths import REPO_ROOT

GROUP_COLORS = {
    "govde": "#5d6b6b",
    "bacak": "#d98c3f",
    "ayak": "#e0612b",
    "aktuator": "#4f9bd9",
    "elektronik": "#4caf7a",
    "batarya": "#d9c24f",
    "sensor": "#b574d9",
    "montaj": "#c9a05a",
    "ithal": "#8d8dff",
}
GROUP_ORDER = (
    "govde",
    "batarya",
    "elektronik",
    "sensor",
    "aktuator",
    "montaj",
    "ithal",
    "bacak",
    "ayak",
)
GROUP_LABEL = {
    "govde": "Gövde",
    "bacak": "Bacak (basılı)",
    "ayak": "Ayak (basılı)",
    "aktuator": "Servo motorlar",
    "elektronik": "Kartlar",
    "batarya": "Batarya",
    "sensor": "Sensörler",
    "montaj": "Montaj parçaları (basılı)",
    "ithal": "İçe aktarılan (GitHub)",
}


def scene_name(genome_id: str) -> str:
    """File name of a genome's scene in the cloud media store; the API derives the same one."""
    return "scene-" + hashlib.sha256(genome_id.encode()).hexdigest()[:12] + ".json"


def ascii_stl_to_binary(source: Path, target: Path) -> Path:
    """FreeCAD writes ASCII STL (about 1 MB a part); binary is a quarter of that."""
    triangles: list[list[float]] = []
    vertices: list[float] = []
    for line in source.read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = line.split()
        if parts[:1] == ["vertex"]:
            vertices += [float(parts[1]), float(parts[2]), float(parts[3])]
            if len(vertices) == 9:
                triangles.append(vertices)
                vertices = []
    out = bytearray(80) + struct.pack("<I", len(triangles))
    for tri in triangles:
        a, b, c = (np.array(tri[i : i + 3]) for i in (0, 3, 6))
        normal = np.cross(b - a, c - a)
        length = float(np.linalg.norm(normal))
        nx, ny, nz = (normal / length).tolist() if length else (0.0, 0.0, 1.0)
        out += struct.pack("<12fH", nx, ny, nz, *tri, 0)  # a zero normal renders black
    target.write_bytes(bytes(out))
    return target


def build_scene(
    genome_id: str,
    body: Mapping[str, Any],
    stl_urls: Mapping[str, str] | None = None,
    step_urls: Mapping[str, str] | None = None,
    mesh_urls: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """The scene JSON of a model: its parts (made by the model through the CAD MCP, or imported) placed by their URDF."""
    imports = list(body["mechanical"].get("imports", []))
    parts = [import_part(placement, i) for i, placement in enumerate(place(imports))]
    order = {g: i for i, g in enumerate(GROUP_ORDER)}
    layout = body["mechanical"].get("layout", {})
    for p in parts:
        p["order"] = order[p["group"]]
        override = layout.get(p["id"], {})
        if "pos" in override:
            p["pos"] = [float(v) for v in override["pos"]]
            p["moved"] = True
        if "size" in override and p["geom"]["type"] != "stl":
            p["geom"]["size"] = [float(v) for v in override["size"]]
            p["moved"] = True
    return {
        "imported": True,
        "generated": bool(body["mechanical"].get("generated")),
        "wiring": [],
        "rig": rig_of_imports(imports),
        "imports": imports,
        "fit": {
            "ok": True,
            "checked": len(parts),
            "issues": [],
            "note": "Uyum denetimi tasarım sırasında (yerleşim eleştirmeni) yapılır.",
        },
        "genome": genome_id,
        "units": "mm",
        "parts": parts,
        "groups": [
            {"id": g, "label": GROUP_LABEL[g], "color": GROUP_COLORS[g]} for g in GROUP_ORDER
        ],
        "bom": bill_of_materials(body),
    }


def import_part(placement: Mapping[str, Any], index: int) -> dict[str, Any]:
    """A part imported from GitHub (mesh or URDF primitive), placed by its URDF, its own coordinates
    or the table; parts of a URDF carry their link and link-frame pose so the viewer can pose them."""
    entry = placement.get("entry")
    shape = placement.get("shape")
    color = placement.get("color") or GROUP_COLORS["ithal"]
    if shape:
        geom: dict[str, Any] = {
            "type": shape["type"],
            "size": [round(float(v), 2) for v in placement["size"]],
        }
        if "radius" in shape:
            geom["radius"] = shape["radius"]
        if "length" in shape:
            geom["length"] = shape["length"]
        info: dict[str, Any] = {
            "şekil": f"URDF {shape['type']}",
            "yerleşim": "URDF'ye göre montajlı",
        }
        files: dict[str, str] | None = None
    else:
        if entry is None:  # a mesh part always comes from an imported entry
            raise ValueError("mesh placement without an entry")
        geom = {
            "type": "stl",
            "url": entry["urls"]["stl"],
            "center": True,
            "size": [round(float(v), 2) for v in placement["size"]],
            "scale": placement["factor"],  # mesh units -> millimetres
        }
        if placement.get("scale3"):
            geom["scale3"] = placement["scale3"]
        if entry["urls"].get("mesh"):
            geom["mesh"] = entry["urls"]["mesh"]  # the compact mesh the viewer downloads first
        layout = (
            "URDF'ye göre montajlı"
            if placement.get("quat")
            else "parça tablosu (her parça kendi çerçevesinde olduğu için dizildi)"
            if placement.get("table")
            else "dosyadaki özgün koordinat"
        )
        info = {"kaynak": entry["source"], "lisans": entry["license"], "yerleşim": layout}
        files = {"stl": entry["urls"]["stl"], "step": entry["urls"].get("step", "")}
        for key, name in (("drawing", "drawing_svg"), ("dxf", "drawing_dxf")):  # the manufacturing drawing of a part the lab designed
            if entry["urls"].get(name):
                files[key] = entry["urls"][name]
    part: dict[str, Any] = {
        "id": placement["id"],
        "label": placement["label"],
        "group": "ithal",
        "geom": geom,
        "pos": list(placement["pos"]),
        "rot": [0, 0, 0],
        "color": color,
        "opacity": 1.0,
        "explode": [(index % 4) * 40.0 - 60.0, 0.0, 60.0],
        "info": info,
    }
    if files:
        part["files"] = files
    if placement.get("quat"):
        part["quat"] = list(placement["quat"])
    if placement.get("link"):
        part["link"] = placement["link"]
        part["local"] = {"pos": list(placement["local_pos"]), "quat": list(placement["local_quat"])}
    return part


def import_rows(imports: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Bill of materials rows of imported items: where they came from and under what licence."""
    return [
        {
            "group": GROUP_LABEL["ithal"],
            "part": f"{e['name']} ({e['kind']})",
            "qty": 1,
            "spec": f"{e['repo']} · lisans: {e['license']}",
            "key": None,
            "specs": [f"sha256 {str(e.get('sha256', ''))[:12]}"] if e.get("sha256") else [],
            "links": [{"label": "kaynak (GitHub)", "url": e["source"], "kind": "ürün"}],
            "estimated": True,
        }
        for e in imports
    ]


# genome model names -> catalog keys (hardware/catalog/parts.yaml)
CATALOG_KEY = {
    "raspberry_pi_5_8gb": "rpi5",
    "stm32f446": "stm32f446",
    "esp32s3": "esp32s3",
    "atmega328p": "atmega328p",
    "sts3215": "sts3215",
    "bno085": "bno085",
    "realsense_d405": "d405",
    "ina226": "ina226",
    "buck_5v5a": "buck_5v5a",
    "ldo_3v3": "ldo_3v3",
}
MATERIAL_KEY = {"PA6-CF": "pa6cf", "TPU": "tpu"}
FASTENER_GROUP = "Bağlantı elemanları (tahmini)"


def load_catalog() -> dict[str, Any]:
    path = REPO_ROOT / "hardware" / "catalog" / "parts.yaml"
    return dict(yaml.safe_load(path.read_text(encoding="utf-8")))


def generated_rows(body: Mapping[str, Any]) -> list[dict[str, Any]]:
    """BOM rows of a robot the lab designed: what to print (material, estimated mass) and what to buy."""
    plan = (body["mechanical"].get("generated") or {}).get("plan") or []
    density = {"PETG": 1.27, "PA6-CF": 1.17, "PLA": 1.24, "ASA": 1.07}
    designs = {
        e["name"]: e.get("design", {})
        for e in body["mechanical"].get("imports", [])
        if e.get("kind") == "stl"
    }
    rows = []
    for lk in plan:
        dims = "×".join(f"{v:g}" for v in lk.get("dims_mm", []))
        if lk.get("source") == "designed":
            d = designs.get(lk["name"], {})
            grams = d.get("volume_mm3", 0) / 1000 * density.get(str(lk.get("material")), 1.2)
            spec = f"{lk.get('material')} · {dims} mm · yaklaşık {grams:.0f} g (CAD hacminden)"
            group = "Basılı parçalar (lab tasarımı)"
        else:
            spec = f"{dims} mm · {lk.get('mass_g', 0):g} g · tedarik edilecek"
            group = "Satın alınanlar"
        rows.append(
            {
                "group": group,
                "part": f"{lk['name']}: {lk.get('role', '')}",
                "qty": 1,
                "spec": spec,
                "key": None,
                "specs": [],
                "links": [],
                "estimated": True,
            }
        )
    return rows


def bill_of_materials(body: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Malzeme listesi: every part with its catalog links and specs, then the fasteners.

    Costs are not on file (prices drift); the catalog stores where to look, not what it costs.
    """
    imports = list(body["mechanical"].get("imports", []))
    if body["morphology"].get("body_type") == "imported":
        return [*generated_rows(body), *import_rows(imports)]
    catalog = load_catalog()["parts"]
    elec, power, make = body["electronics"], body["power"], body["manufacturing"]
    servos = int(elec["actuators"]["count"])

    def row(group: str, part: str, qty: int, spec: str, key: str | None) -> dict[str, Any]:
        entry = catalog.get(key or "", {})
        return {
            "group": group,
            "part": part,
            "qty": qty,
            "spec": spec,
            "key": key,
            "specs": list(entry.get("specs", [])),
            "links": list(entry.get("links", [])),
            "estimated": False,
        }

    rows = [
        row(
            "aktuator",
            f"Servo {elec['actuators']['model']}",
            servos,
            f"kalkış torku {elec['actuators']['stall_torque_nm']} Nm",
            CATALOG_KEY.get(elec["actuators"]["model"]),
        ),
        row(
            "elektronik",
            f"Ana bilgisayar {elec['compute']['model']}",
            1,
            "",
            CATALOG_KEY.get(elec["compute"]["model"]),
        ),
    ]
    for label, block in (
        ("Hareket kartı", "motion_controller"),
        ("Yardımcı kart", "aux_mcu"),
        ("Güvenlik kartı", "safety_mcu"),
    ):
        rows.append(
            row(
                "elektronik",
                f"{label} {elec[block]['model']}",
                1,
                elec[block]["firmware"],
                CATALOG_KEY.get(elec[block]["model"]),
            )
        )
    battery = power["battery"]
    rows.append(
        row(
            "batarya",
            f"Batarya {battery['cells']}S {battery['capacity_mah']} mAh",
            1,
            f"{battery['chemistry']} · {battery['c_rating']}C · BMS {power['bms']}",
            "lipo_4s",
        )
    )
    for r in power["rails"]:
        rows.append(
            row(
                "elektronik",
                f"Regülatör {r['converter']}",
                1,
                f"{r['v']} V, en çok {r['a_max']} A",
                CATALOG_KEY.get(r["converter"]),
            )
        )
    for sensor in elec["sensors"]:
        rate = f"{sensor['rate_hz']} Hz" if sensor.get("rate_hz") else ""
        rows.append(
            row(
                "sensor",
                f"{sensor['type']} {sensor['model']}",
                int(sensor.get("count", 1)),
                rate,
                CATALOG_KEY.get(sensor["model"]),
            )
        )
    rows.append(
        row(
            "govde",
            "Gövde kabuğu",
            1,
            f"{make['print_time_h']} sa baskı (toplam), {make['assembly_time_h']} sa montaj",
            None,
        )
    )

    counts = {"servo": servos}
    fasteners = load_catalog()["fasteners"]
    for f in fasteners:
        qty = int(f.get("qty_fixed", 0)) + sum(
            counts.get(k, 0) * n for k, n in f.get("qty_per", {}).items()
        )
        rows.append(
            {
                "group": "baglanti",
                "part": f["title"],
                "qty": qty,
                "spec": f["basis"],
                "key": f["key"],
                "specs": list(f.get("specs", [])),
                "links": list(f.get("links", [])),
                "estimated": True,
            }
        )
    return [
        {**r, "group": GROUP_LABEL.get(r["group"], FASTENER_GROUP)} for r in rows
    ] + import_rows(imports)


def stl_bounds(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Min and max corner of a binary STL (used by tests and for sanity checks)."""
    data = path.read_bytes()
    count = struct.unpack("<I", data[80:84])[0]
    raw = np.frombuffer(
        data[84:],
        dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]),
        count=count,
    )
    flat = raw["v"].reshape(-1, 3)
    return flat.min(axis=0), flat.max(axis=0)
