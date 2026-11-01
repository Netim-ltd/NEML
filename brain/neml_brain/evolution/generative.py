# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Robots designed by the language model through the MCP tools, with no parametric template.

1. plan     - the model states the robot as a tree of links (a part, where it joins its parent, how it
              moves, its mass), under a JSON schema;
2. parts    - every designed link gets a CSG recipe (boxes, cylinders, spheres, cut/fuse; plain data,
              nothing the model writes is executed) that the CAD MCP builds in FreeCAD into STL + STEP;
              a failed build goes back to the model with the error, three times at most; bought parts
              (servos, batteries, boards) are primitives with the bought part's dimensions;
3. assemble - a URDF is written from the plan and read by the same assembler as imported robots, so
              the 3D view, joint posing, collision and balance checks, screw plan and BOM all work;
4. gates    - structure, mass, size and tree checks (analysts); a design that passes becomes the model's
              active design *in simulation* by itself. Printing and building it still go through the
              owner's approval (manufacture gate) like every other design.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

import sqlalchemy as sa
import structlog

from neml_brain.evolution import structure
from neml_brain.evolution.buildpack import build_pack
from neml_brain.evolution.catalog import CATALOG, OTHER
from neml_brain.evolution.catalog import apply as use_catalog
from neml_brain.evolution.catalog import listing as catalog_text
from neml_brain.evolution.judges import (
    equip,
    recipe_issues,
    robot_issues,
    softer_rounds,
    thickened,
    tidy,
    without_cuts,
)
from neml_brain.evolution.urdf_assembly import UrdfError, assemble
from neml_brain.llm.provider import SchemaViolation
from neml_brain.llm.schemas import MECH_PARAM_SCHEMA as RECIPE_SCHEMA

log = structlog.get_logger(__name__)

MAX_LINKS = 24
MAX_ATTEMPTS = 3
DENSITY = {"PETG": 1.27, "PA6-CF": 1.17, "PLA": 1.24, "ASA": 1.07}  # g/cm3
NUM = {"type": "number"}

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["name", "purpose", "root", "links"],
    "properties": {
        "name": {"type": "string", "maxLength": 30},
        "purpose": {"type": "string", "maxLength": 200},
        "root": {
            "type": "object",
            "required": ["name", "role", "source", "dims_mm", "mass_g"],
            "properties": {
                "name": {"type": "string", "maxLength": 24},
                "role": {"type": "string", "maxLength": 120},
                "source": {"enum": ["designed", "bought"]},
                "part": {"enum": [*CATALOG, OTHER]},
                "material": {"enum": ["PETG", "PA6-CF", "PLA", "ASA"]},
                "dims_mm": {
                    "type": "array",
                    "minItems": 3,
                    "maxItems": 3,
                    "items": {"type": "number", "minimum": 1, "maximum": 600},
                },
                "mass_g": {"type": "number", "minimum": 1, "maximum": 5000},
            },
        },
        "links": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_LINKS - 1,
            "items": {
                "type": "object",
                "required": ["name", "parent", "role", "source", "dims_mm", "mass_g", "joint"],
                "properties": {
                    "name": {"type": "string", "maxLength": 24},
                    "parent": {"type": "string", "maxLength": 24},
                    "role": {"type": "string", "maxLength": 120},
                    "source": {"enum": ["designed", "bought"]},
                    "part": {"enum": [*CATALOG, OTHER]},
                    "material": {"enum": ["PETG", "PA6-CF", "PLA", "ASA"]},
                    "dims_mm": {
                        "type": "array",
                        "minItems": 3,
                        "maxItems": 3,
                        "items": {"type": "number", "minimum": 1, "maximum": 600},
                    },
                    "mass_g": {"type": "number", "minimum": 1, "maximum": 5000},
                    "joint": {
                        "type": "object",
                        "required": ["type", "x", "y", "z", "axis"],
                        "properties": {
                            "type": {"enum": ["fixed", "revolute"]},
                            "x": NUM,
                            "y": NUM,
                            "z": NUM,
                            "axis": {"enum": ["x", "y", "z"]},
                            "lower_deg": NUM,
                            "upper_deg": NUM,
                        },
                    },
                },
            },
        },
    },
}
IDEA_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["idea", "why"],
    "properties": {
        "idea": {"type": "string", "maxLength": 300},
        "why": {"type": "string", "maxLength": 200},
    },
}

PLAN_PROMPT = (
    "Bir robot tasarla: {brief}\n"
    "Robotu bağlantı (link) ağacı olarak yaz. Birimler mm ve gram. 'root' ana gövdedir (parent'ı yoktur); 'links' root'a ve birbirine bağlanan diğer parçalardır, "
    "her birinin parent'ı root'un ya da daha önce yazılmış bir linkin adı olmalı. "
    "Her link: name (küçük harf, rakam, alt çizgi), parent, role, source ('designed' = bizim basacağımız/işleyeceğimiz parça, "
    "'bought' = servo, batarya, kart, motor, tekerlek, sensör gibi satın alınan parça; bought ise 'part' alanına aşağıdaki katalogdan bir kimlik yaz, boyut ve kütle katalogdan alınır), dims_mm [uzunluk, genişlik, yükseklik], mass_g, "
    "joint (parent'a bağlandığı yer x,y,z mm cinsinden parent çerçevesinde; fixed ya da revolute; revolute için axis ve lower_deg/upper_deg). "
    "Parçalar birbirinin içine girmesin; servoyu hareket ettireceği parçanın eklem noktasına koy. En az 2, en çok {max} link. JSON'u boşluksuz, tek satırda yaz.\n"
    "Hareketli robotta kontrolcü kartı, batarya ve acil durdurma düğmesi (estop_22mm) olmalı; her döner eklem için yeterli torklu servo/DC motor seç.\n"
    "Katalog:\n{catalog}\n"
    "Bilinen notlar:\n{notes}"
)
PART_PROMPT = (
    "Bu parçanın 3B tarifini (CSG) yaz: '{name}' - {role}. Yaklaşık {dims} mm, malzeme {material}.\n"
    "Önce plan alanına 2-3 cümle yaz: ana gövde nedir, hangi özellikler (delik, kabuk, yuvarlama) nereye gelir, hangi ölçüler sabit. Sonra tarifi bu plana göre yaz. "
    "Tarif: solids şunlardan oluşur: box (at=köşe, size=[l,w,h]), cyl (at=taban merkezi, r, h, axis), cone (at, r, r2, h, axis), sphere (at=merkez, r), "
    "prism (2B kesiti kalınlık verip çıkar: plane xy|xz|yz, pts=[[u,v],...] köşeler, h=kalınlık, at=çizimin başlangıcı; bir köşeye üçüncü sayı eklersen [u,v,bulge] o köşeden sonrakine yay çizer: bulge 1 yarım daire, 0.4 yaklaşık çeyrek yay, eksi sayı ters yön; "
    "iki köşe [[0,0,1],[20,0,1]] ile daire, r ile de daire çizilir), turn (kesiti eksen etrafında döndür: plane, pts, about u|v, angle), loft (iki kesit arası: pts, pts2 aynı sayıda köşe, h), "
    "pipe (r, ri, path=[[x,y,z],...] boyunca boru), array (of=önceki bir solid, n, step=[dx,dy,dz]), polar (of, n, axis, at=merkez, angle) ve mirror (of, plane). "
    "steps (cut ya da fuse: a, b, out) ve result (son parçanın id'si). "
    "İstersen features: hole {{kind plain|cbore|csink|tap, at=yüzeydeki nokta, axis, dir '-' ya da '+' (malzemenin içine doğru), d, depth (yoksa boydan boya), d2 ve depth2 (havşa/alın), tap için d=M ölçüsü}} ve shell {{t, open: 'z+'}}; "
    "round: {{kind: fillet|chamfer, r: mm, edges: all|vertical|top|bottom}}. Ana boyutları spec: [{{axis, value, tol}}] olarak yaz, lab ölçüp doğrular. Birimler mm. "
    "Parçanın kendi çerçevesinin başlangıç noktası (0,0,0), bu parçanın üst parçaya bağlandığı eklem noktasıdır; parça bu noktanın etrafında/yakınında yer alsın. "
    "Kurallar: duvar en az 1.6 mm, vida deliği 3.2 mm (hole ile ya da cyl'i cut ile), köşeler kare olabilir, tek parça ve birleşik olsun. Kutu ve silindirle olmayan şekilleri (yay, eğri, dönel gövde) prism/turn ile çiz.{rules}{error}"
)


TR = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
NAME = re.compile(r"[^a-z0-9]+")


MAX_RESUMES = 4  # a design that keeps dying with the process is given up


def model_name(name: str) -> str:
    """A safe model identifier: Turkish letters folded, lowercase, starts with a letter, at most 24 characters."""
    cleaned = NAME.sub("_", name.lower().translate(TR)).strip("_")[:24]
    return cleaned if re.match(r"^[a-z]", cleaned) else f"model_{cleaned}".strip("_")[:24]


def slug(text: str, limit: int = 24) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:limit] or "x"


def normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """The model's {root, links} as one list: the root first, joined to nothing."""
    root = {
        **raw["root"],
        "parent": "",
        "joint": {"type": "fixed", "x": 0, "y": 0, "z": 0, "axis": "z"},
    }
    return use_catalog({**raw, "links": [root, *raw["links"]]})


TERRAIN_ADVICE = (  # (word in the world name, advice for a robot that keeps losing there)
    ("stair", "merdiven: basamaktan büyük çaplı tekerlek/ayak ya da bacaklı yürüyüş, yüksek torklu aktüatör"),
    ("ramp", "rampa: yüksek torklu motor, yüksek sürtünmeli lastik/ayak, alçak ağırlık merkezi"),
    ("obstacle", "engel: yerden yüksek gövde, büyük tekerlek"),
)


def sim_hint(root: Path) -> str:
    """What the lab's own simulation runs say about the robots it has: terrains where they keep losing, and why, as advice for the
    next plan. Nothing before 20 runs (a few failures are noise). # ponytail: advice is per terrain word, not per failure physics."""
    try:
        rec = json.loads((root / "sweeps.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if int(rec.get("runs", 0)) < 20:
        return ""
    lines = []
    passes, fails = rec.get("passes", {}), rec.get("fails", {})
    for world, why in fails.items():
        if passes.get(world, 0) > 0:
            continue
        advice = next((a for w, a in TERRAIN_ADVICE if w in world), "")
        reason = "devrildi: tabanı genişlet, ağırlık merkezini alçalt" if why.get("tipped") else f"hedefe varamadı ({why.get('x_m')} m gitti)"
        lines.append(f"- {world}: {reason}" + (f"; {advice}" if advice else ""))
    return ("\n\nSimülasyonda mevcut robotlar şu ortamlarda başarısız oluyor; planı buna göre güçlendir:\n" + "\n".join(lines[:5])) if lines else ""


def check_plan(plan: dict[str, Any]) -> list[str]:
    """Why a plan cannot be built (empty = fine): one root, parents before children, unique names, sane mass."""
    links = plan.get("links") or []
    names: list[str] = []
    problems = []
    roots = [lk for lk in links if not str(lk.get("parent", "")).strip()]
    if len(roots) != 1:
        problems.append(f"tam olarak bir kök link olmalı (parent boş), {len(roots)} var")
    for lk in links:
        name = slug(str(lk["name"]))
        parent = slug(str(lk["parent"])) if str(lk.get("parent", "")).strip() else ""
        if name in names:
            problems.append(f"{name} iki kez tanımlı")
        if parent and parent not in names:
            problems.append(f"{name}: parent '{parent}' önceden tanımlı değil")
        names.append(name)
        if lk["source"] == "designed" and "material" not in lk:
            lk["material"] = "PETG"
    total = sum(float(lk["mass_g"]) for lk in links) / 1000
    if not 0.05 <= total <= 30:
        problems.append(f"toplam kütle {total:.2f} kg: 0,05–30 kg arası olmalı")
    return problems


def layout(plan: dict[str, Any]) -> tuple[dict[str, list[float]], dict[str, list[float]], dict[str, str]]:
    """Where every link sits (centre of its box, joints added up the tree), its size and its parent."""
    centre: dict[str, list[float]] = {}
    size: dict[str, list[float]] = {}
    parent: dict[str, str] = {}
    for lk in plan["links"]:
        name = slug(str(lk["name"]))
        up = slug(str(lk["parent"])) if str(lk.get("parent", "")).strip() else ""
        j = lk["joint"]
        base = centre[up] if up else [0.0, 0.0, 0.0]
        centre[name] = [base[0] + float(j["x"]), base[1] + float(j["y"]), base[2] + float(j["z"])]
        size[name] = [float(v) for v in lk["dims_mm"]]
        parent[name] = up
    return centre, size, parent


def tip_margin(plan: dict[str, Any]) -> float:
    """Half the narrower footprint side over the height of the centre of mass above the floor (centre of mass of boxes at their joints)."""
    centre, size, _ = layout(plan)
    mass = {slug(str(lk["name"])): float(lk["mass_g"]) for lk in plan["links"]}
    total = sum(mass.values())
    floor = min(centre[n][2] - size[n][2] / 2 for n in centre)
    com = [sum(mass[n] * centre[n][k] for n in centre) / total for k in range(3)]
    spans = [max(centre[n][k] + size[n][k] / 2 for n in centre) - min(centre[n][k] - size[n][k] / 2 for n in centre) for k in (0, 1)]
    return min(spans) / 2 / max(com[2] - floor, 1.0)


def plan_score(plan: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    """How good a plan looks before anything is built (higher wins): few layout and robot-rule problems first, then a low centre of
    mass over a wide footprint, then fewer links."""
    tip = tip_margin(plan)
    issues = len(layout_issues(plan)) + len(robot_issues(plan))
    info = {"layout_issues": issues, "tip_margin": round(tip, 2), "links": len(plan["links"])}
    return -3.0 * issues + min(tip, 2.0) - 0.02 * len(plan["links"]), info


VARIANT_HINTS = [
    "",
    "\nBu kez farklı bir yaklaşım dene: daha az ve daha sağlam parça, basit bir yapı.",
    "\nBu kez farklı bir yaklaşım dene: geniş taban ve alçak ağırlık merkezi, devrilmeme öncelikli.",
]


def _overlap(ca: list[float], sa: list[float], cb: list[float], sb: list[float]) -> float:
    v = 1.0
    for k in range(3):
        v *= max(min(ca[k] + sa[k] / 2, cb[k] + sb[k] / 2) - max(ca[k] - sa[k] / 2, cb[k] - sb[k] / 2), 0.0)
    return v


def _clash(c: list[float], name: str, up: str, placed: list[str], centre: dict[str, list[float]], size: dict[str, list[float]]) -> bool:
    for other in placed:
        small = min(size[name][0] * size[name][1] * size[name][2], size[other][0] * size[other][1] * size[other][2])
        if _overlap(c, size[name], centre[other], size[other]) > (0.6 if other == up else 0.2) * small:
            return True
    return False


def repair_layout(plan: dict[str, Any]) -> dict[str, Any]:
    """A small constraint solver for plans whose links sit inside each other: parents first, each link that overlaps something placed
    before it is moved to a face of its parent (the direction it already pointed in first, then the other five) until nothing
    overlaps. The joint offsets are rewritten; everything else in the plan is left alone."""
    out = deepcopy(plan)
    centre, size, parent = layout(out)
    placed: list[str] = []
    for lk in out["links"]:
        name = slug(str(lk["name"]))
        up = parent[name]
        if up:
            if _clash(centre[name], name, up, placed, centre, size):
                j = lk["joint"]
                lead = max(range(3), key=lambda k: abs((float(j["x"]), float(j["y"]), float(j["z"]))[k]))
                tried = [(lead, 1 if (float(j["x"]), float(j["y"]), float(j["z"]))[lead] >= 0 else -1)]
                tried += [(k, d) for k in (0, 1, 2) for d in (1, -1) if (k, d) != tried[0]]
                for k, d in tried:
                    c = list(centre[up])
                    c[k] += d * (size[up][k] + size[name][k]) / 2
                    if not _clash(c, name, up, placed, centre, size):
                        centre[name] = c
                        for axis, key in enumerate("xyz"):
                            j[key] = round(c[axis] - centre[up][axis], 1)
                        break
        placed.append(name)
    return out


def layout_issues(plan: dict[str, Any]) -> list[str]:
    """The plan's geometry as a critic would read it: every link is a box centred where its joint is (no rotations).

    Two unrelated links may not share volume, a link must touch the part it hangs on. Returns the problems with
    the measured numbers, which go back to the model in the next attempt.
    """
    centre, size, parent = layout(plan)
    issues = []
    names = list(centre)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            overlap = 1.0
            for k in range(3):
                lo = max(centre[a][k] - size[a][k] / 2, centre[b][k] - size[b][k] / 2)
                hi = min(centre[a][k] + size[a][k] / 2, centre[b][k] + size[b][k] / 2)
                overlap *= max(hi - lo, 0.0)
            small = min(size[a][0] * size[a][1] * size[a][2], size[b][0] * size[b][1] * size[b][2])
            related = parent[a] == b or parent[b] == a
            if overlap > (0.6 if related else 0.2) * small:
                issues.append(
                    f"{a} ve {b} iç içe giriyor (küçük olanın %{100 * overlap / small:.0f}'i ortak hacim)"
                )
    for name, up in parent.items():
        if not up:
            continue
        gap = max(
            max(abs(centre[name][k] - centre[up][k]) - (size[name][k] + size[up][k]) / 2, 0.0)
            for k in range(3)
        )
        if gap > 15:
            issues.append(
                f"{name}, bağlı olduğu {up} parçasına değmiyor (boşluk {gap:.0f} mm); eklem konumunu parçaya yaklaştır"
            )
    return issues


def urdf_of(plan: dict[str, Any], meshes: dict[str, str]) -> str:
    """The robot as URDF text (metres): designed links use their STL (scaled mm->m), bought ones a box."""
    out = [f'<robot name="{slug(plan["name"])}">']
    joints = []
    for lk in plan["links"]:
        name = slug(str(lk["name"]))
        mass = float(lk["mass_g"]) / 1000
        if name in meshes:
            geom = f'<mesh filename="{meshes[name]}" scale="0.001 0.001 0.001"/>'
        else:
            bx, by, bz = (float(v) / 1000 for v in lk["dims_mm"])
            geom = f'<box size="{bx:.4f} {by:.4f} {bz:.4f}"/>'
        color = "0.8 0.5 0.2 1" if lk["source"] == "designed" else "0.25 0.3 0.4 1"
        out.append(
            f'<link name="{name}"><visual><geometry>{geom}</geometry><material name="m_{name}"><color rgba="{color}"/></material></visual>'
            f'<inertial><origin xyz="0 0 0"/><mass value="{mass:.4f}"/><inertia ixx="{mass * 1e-4:.6f}" ixy="0" ixz="0" iyy="{mass * 1e-4:.6f}" iyz="0" izz="{mass * 1e-4:.6f}"/></inertial></link>'
        )
        if str(lk.get("parent", "")).strip():
            j = lk["joint"]
            axis = {"x": "1 0 0", "y": "0 1 0", "z": "0 0 1"}[j["axis"]]
            kind = "revolute" if j["type"] == "revolute" else "fixed"
            limit = (
                f'<limit lower="{math.radians(float(j.get("lower_deg", -60))):.4f}" upper="{math.radians(float(j.get("upper_deg", 60))):.4f}" effort="3" velocity="6"/>'
                if kind == "revolute"
                else ""
            )
            joints.append(
                f'<joint name="j_{name}" type="{kind}"><parent link="{slug(str(lk["parent"]))}"/><child link="{name}"/>'
                f'<origin xyz="{float(j["x"]) / 1000:.4f} {float(j["y"]) / 1000:.4f} {float(j["z"]) / 1000:.4f}" rpy="0 0 0"/><axis xyz="{axis}"/>{limit}</joint>'
            )
    return "\n".join([*out, *joints, "</robot>"])


def gate(plan: dict[str, Any], built: dict[str, dict[str, Any]]) -> list[str]:
    """Blocking problems of a built design (empty = it may become the active simulation design)."""
    problems = []
    for lk in plan["links"]:
        info = built.get(slug(str(lk["name"])))
        if lk["source"] != "designed" or info is None:
            continue
        bb = info["bbox"]
        size = [bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]]
        mass_g = info["volume_mm3"] / 1000 * DENSITY.get(str(lk.get("material")), 1.2)
        if max(size) > 600:
            problems.append(f"{lk['name']}: {max(size):.0f} mm, 600 mm sınırını aşıyor")
        for f in structure.generic_link(
            size, info["volume_mm3"], str(lk.get("material")), float(plan_mass(plan)), mass_g
        ):
            if f["severity"] == "high":
                problems.append(f["text"])
    return problems


def plan_mass(plan: dict[str, Any]) -> float:
    return sum(float(lk["mass_g"]) for lk in plan["links"]) / 1000


class Generator:
    def __init__(
        self,
        mcp: Any,
        importer: Any,
        sessions: Any,
        llm: Any,
        learn: Any,
        work: Path,
        notes: Any = None,
    ) -> None:
        self._mcp, self._imp, self._sessions, self._llm, self._learn = (
            mcp,
            importer,
            sessions,
            llm,
            learn,
        )
        self._work, self._notes = work, notes
        self._jobs = work / "jobs.json"
        self._running: set[asyncio.Task[Any]] = set()
        self.rules: list[str] = []  # recipe rules the lab found by itself (evolution/bench.py Evolver)
        self.skills: Any = None  # SkillLibrary: checked recipes shown to the model as examples (main.py sets it)
        self.on_findings: Any = None  # called with the judges' findings of a plan (the data steward labels them)
        self.variants = 1  # plans raced per design (main.py raises it)
        self.on_done: Any = None  # called with the finished design's result (the round table meets)

    # ------------------------------------------------------------- jobs
    def jobs(self) -> list[dict[str, Any]]:
        try:
            return list(json.loads(self._jobs.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return []

    def _save(self, job: dict[str, Any]) -> None:
        jobs = [j for j in self.jobs() if j["id"] != job["id"]] + [job]
        self._work.mkdir(parents=True, exist_ok=True)
        self._jobs.write_text(json.dumps(jobs[-40:], ensure_ascii=False), encoding="utf-8")

    def busy(self) -> bool:
        return any(
            j["state"] == "running" and time.time() - j["at"] < 4 * 3600 for j in self.jobs()
        )

    def start(self, brief: str, actor: str, auto_activate: bool = True) -> dict[str, Any]:
        """Begin a design in the background (it takes many minutes on this CPU); progress is kept in the job."""
        job = {
            "id": uuid.uuid4().hex[:8],
            "brief": brief[:400],
            "actor": actor,
            "state": "running",
            "steps": ["başladı"],
            "at": time.time(),
            "auto_activate": auto_activate,
            "ckpt": {},
        }
        self._save(job)
        task = asyncio.create_task(self._run(job, auto_activate))
        self._running.add(task)
        task.add_done_callback(self._running.discard)
        return job

    def resume(self) -> int:
        """After a restart: designs that were running go on from their last checkpoint (the plan and the parts already built)."""
        n = 0
        for job in self.jobs():
            if job["state"] != "running" or job.get("resumes", 0) >= MAX_RESUMES:
                if job["state"] == "running":
                    job.update(state="failed", error="çok kez yeniden başlatıldı")
                    self._save(job)
                continue
            job["resumes"] = job.get("resumes", 0) + 1
            self._step(job, "yeniden başlatma sonrası kaldığı yerden devam ediyor")
            task = asyncio.create_task(self._run(job, bool(job.get("auto_activate", True))))
            self._running.add(task)
            task.add_done_callback(self._running.discard)
            n += 1
        return n

    def _step(self, job: dict[str, Any], text: str) -> None:
        job["steps"] = [*job["steps"][-30:], text]
        self._save(job)

    async def _run(self, job: dict[str, Any], auto_activate: bool) -> None:
        try:
            result = await self.design(
                job["brief"],
                job["actor"],
                lambda t: self._step(job, t),
                auto_activate,
                job.setdefault("ckpt", {}),
                lambda: self._save(job),
            )
            job.update(state="done", result=result)
            job.pop("ckpt", None)
        except Exception as exc:  # noqa: BLE001 - a failed design is a finding, not a crash
            log.warning("generative.failed", error=repr(exc)[:200])
            if not job.get("retried"):  # once more from the checkpoint: a busy or restarted model is the usual cause
                job.update(retried=True)
                self._step(job, f"hata ({type(exc).__name__}), kaldığı yerden bir kez daha deneniyor")
                return await self._run(job, auto_activate)
            job.update(state="failed", error=(str(exc) or type(exc).__name__)[:300])
            self._learn.note(
                "cad",
                "generative_failed",
                f"tasarım başarısız ({job['brief'][:60]}): {str(exc)[:120]}",
            )
        job["steps"] = [*job["steps"][-30:], job["state"]]
        self._save(job)
        if job["state"] == "done" and self.on_done is not None:
            try:
                await self.on_done(job["result"])
            except Exception as exc:  # noqa: BLE001 - the review is a follow-up, never a failure of the design
                log.warning("generative.review_failed", error=str(exc)[:200])

    # ----------------------------------------------------------- the design
    async def _plan(self, brief: str, progress: Any, hint: str = "") -> dict[str, Any]:
        notes = ""
        if self._notes is not None:
            notes = (
                "\n".join(f"- {n['title']}: {n['rule']}" for n in self._notes.relevant(brief, 6))
                or "(yok)"
            )
        problem = ""
        best: dict[str, Any] | None = None
        for attempt in range(MAX_ATTEMPTS):
            progress(f"plan {attempt + 1}")
            try:
                raw = await self._llm.fill(
                    PLAN_PROMPT.format(brief=brief, max=MAX_LINKS, notes=notes or "(yok)", catalog=catalog_text()) + hint + sim_hint(self._learn.root) + problem,
                    PLAN_SCHEMA,
                    profile="param_skill",
                    max_tokens=4000,
                )
            except SchemaViolation as exc:  # cut off or off-grammar: say so and ask again
                problem = f"\n\nÖnceki cevap kullanılamadı ({str(exc)[:80]}). Daha kısa ve sade bir plan yaz."
                continue
            plan = normalize(raw)
            issues = check_plan(plan)
            if issues:
                problem = "\n\nÖnceki planın hataları: " + "; ".join(issues) + ". Düzelt."
                continue
            plan = equip(plan)  # the controller, battery, stop switch and actuators a moving robot needs come from the catalog
            best = plan
            layout = [*layout_issues(plan), *robot_issues(plan)]
            if not layout:
                return dict(plan)
            progress(f"yerleşim eleştirisi: {len(layout)} sorun")
            if self.on_findings is not None:
                self.on_findings(layout)
            listing = "; ".join(
                f"{lk['name']} (parent {lk['parent'] or '-'}, eklem {lk['joint']['x']:g},{lk['joint']['y']:g},{lk['joint']['z']:g}, boyut {'x'.join(f'{v:g}' for v in lk['dims_mm'])})"
                for lk in plan["links"]
            )
            problem = (
                f"\n\nÖnceki planın yerleşim sorunları: {'; '.join(layout[:6])}. Önceki plan: {listing}. "
                "Eklem konumlarını (parent çerçevesinde, mm) düzelt: parçalar birbirinin içine girmesin ama bağlı olduğu parçaya değsin."
            )
        if best is not None:  # still imperfect after the revisions: the layout solver moves the links apart
            fixed = repair_layout(best)
            before, after = len(layout_issues(best)), len(layout_issues(fixed))
            progress(f"yerleşim çözücü: {before} sorun -> {after}")
            self._learn.note("cad", "layout", f"plan yerleşimi modelde düzelmedi ({brief[:60]}); çözücü {before}->{after}")
            return fixed if after < before else dict(best)
        raise RuntimeError("plan geçerli çıkmadı: " + problem[-200:])

    async def _race(self, brief: str, progress: Any) -> dict[str, Any]:
        """`variants` different plans for the same request, scored before anything is built; the best one is built."""
        if self.variants < 2:
            return await self._plan(brief, progress)
        scored: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
        for i in range(self.variants):
            try:
                plan = await self._plan(brief, lambda t, i=i: progress(f"varyant {i + 1}: {t}"), VARIANT_HINTS[i % len(VARIANT_HINTS)])
            except RuntimeError:  # a variant that never became a valid plan just loses
                continue
            score, info = plan_score(plan)
            progress(f"varyant {i + 1} ({plan['name']}): {info['links']} link, yerleşim sorunu {info['layout_issues']}, devrilme payı {info['tip_margin']}")
            scored.append((score, plan, info))
        if not scored:
            raise RuntimeError("hiçbir varyant geçerli plan çıkarmadı")
        score, plan, info = max(scored, key=lambda t: t[0])
        progress(f"kazanan: {plan['name']} (puan {score:.2f}, {len(scored)} varyant yarıştı)")
        self._learn.note("design", "variant_race", f"{brief[:60]}: kazanan {info}, puanlar {[round(t[0], 2) for t in scored]}", once=True)
        return plan

    async def _part(
        self, lk: dict[str, Any], out: Path, progress: Any, rules: list[str] | None = None, body_kg: float = 0.0
    ) -> dict[str, Any]:
        name = slug(str(lk["name"]))
        error = ""
        learned = "".join(f" Öğrenilmiş kural: {r}" for r in (self.rules if rules is None else rules))
        if self.skills is not None:
            learned += self.skills.examples(f"{lk['role']} {lk.get('name', '')}", lk.get("case"))
        for attempt in range(MAX_ATTEMPTS):
            progress(f"{name}: parça tarifi {attempt + 1}")
            recipe = await self._llm.fill(
                PART_PROMPT.format(
                    name=name,
                    role=lk["role"],
                    dims=" x ".join(f"{v:g}" for v in lk["dims_mm"]),
                    material=lk.get("material", "PETG"),
                    rules=learned,
                    error=error,
                ),
                RECIPE_SCHEMA,
                profile="param_skill",
                max_tokens=1500,
            )
            recipe = tidy(recipe)  # harmless noise is mended, not sent back
            flaws = recipe_issues(recipe)
            try:
                built = await self._mcp.call(
                    "freecad",
                    "build_recipe",
                    {"recipe": recipe, "out_dir": str(out), "name": name, "process": "print"},
                    120,
                )
                built["recipe"] = recipe
                bb = built["bbox"]
                weak = structure.generic_link(  # the same beam check the gate runs later: a part that fails it is redone now, while the model is on it
                    [bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]], built["volume_mm3"], str(lk.get("material", "PETG")), body_kg, float(lk["mass_g"])
                ) if body_kg else []
                if weak and attempt < MAX_ATTEMPTS - 1:
                    error = f"\n\nÖnceki tarif yapısal olarak zayıf: {weak[0]['text']}. Kesiti kalınlaştır (en az 6 mm) ya da parçayı kısalt."
                    continue
                hard = [d["text"] for d in built.get("dfm", []) if d.get("severity") == "high"]
                if hard and attempt < MAX_ATTEMPTS - 1:  # a manufacturing finding the printer cannot live with goes back to the model, like a wrong size
                    error = "\n\nÜretilebilirlik sorunu: " + "; ".join(hard[:3]) + ". Tarifi düzelt."
                    continue
                off = [c for c in built.get("spec_checks", []) if not c["ok"]]
                if off and attempt < MAX_ATTEMPTS - 1:
                    error = "\n\nÖnceki tarifin ölçüleri tutmadı: " + "; ".join(f"{c['axis']} boyu {c['measured']} mm çıktı, {c['wanted']} ±{c['tol']} olmalı" for c in off) + ". Düzelt."
                    continue
                for section in (6.0, 9.0, 12.0) if weak else ():  # the model's last try is still too thin: the lab thickens it, step by step
                    sturdy = thickened(recipe, bb, section)
                    again = await self._mcp.call("freecad", "build_recipe", {"recipe": sturdy, "out_dir": str(out), "name": name, "process": "print"}, 120)
                    bb2 = again["bbox"]
                    weak = structure.generic_link([bb2[3] - bb2[0], bb2[4] - bb2[1], bb2[5] - bb2[2]], again["volume_mm3"], str(lk.get("material", "PETG")), body_kg, float(lk["mass_g"]))
                    built, recipe = again, sturdy
                    built["recipe"] = recipe
                    if not weak:
                        flaws = [*flaws, f"kesit {section:g} mm'ye kalınlaştırıldı"]
                        break
                built["quality"] = [*flaws, *(f["text"] for f in weak)]
                return dict(built)
            except Exception as exc:  # noqa: BLE001 - the CAD server's message is exactly what the model needs
                mends = without_cuts(recipe) if "not a valid solid" in str(exc) else softer_rounds(recipe) if "does not fit" in str(exc) else []
                if mends:  # an empty result or a rounding that does not fit: mend the recipe before asking the model again
                    for note, mended in mends:
                        try:
                            built = await self._mcp.call("freecad", "build_recipe", {"recipe": mended, "out_dir": str(out), "name": name}, 120)
                        except Exception:  # noqa: BLE001, S112
                            continue
                        log.info("part.mended", part=name, note=note)
                        return {**built, "recipe": mended, "quality": [*flaws, note]}
                log.info("part.build_failed", part=name, attempt=attempt, error=str(exc)[:160], solids=len(recipe.get("solids", [])), steps=len(recipe.get("steps", [])))
                error = f"\n\nÖnceki tarif reddedildi/başarısız: {str(exc)[:200]}. Düzelt."
        raise RuntimeError(f"{name}: parça üretilemedi ({error[-160:]})")

    CAD_TOOLS = ("fit", "standard_part", "drawing", "build_recipe", "fem", "assemble")

    async def cad(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        """One CAD tool for an operator (panel, assistant): results land in the lab's work folder and the files come back as media URLs."""
        if tool not in self.CAD_TOOLS:
            raise ValueError(f"tool must be one of {', '.join(self.CAD_TOOLS)}")
        args = dict(args)
        if tool != "fit":
            folder = self._work / "cad"
            folder.mkdir(parents=True, exist_ok=True)
            args["out_dir"] = str(folder)
            if tool != "fem":
                args.setdefault("name", f"cad_{uuid.uuid4().hex[:8]}")
        res = await self._mcp.call("freecad", tool, args, 300)
        urls: dict[str, str] = {}
        for key in ("stl", "step", "svg", "dxf"):
            path = res.get(key) if isinstance(res, dict) else None
            if isinstance(path, str) and Path(path).is_file():
                url = await self._imp._uploader.upload(Path(path), key)  # noqa: SLF001
                if url:
                    urls[key] = url
        return {"tool": tool, "result": {k: v for k, v in res.items() if k not in ("stl", "step", "svg", "dxf", "threemf")}, "urls": urls}

    async def _draw(self, key: str, info: dict[str, Any], lk: dict[str, Any], out: Path) -> None:
        """The manufacturing drawing of a built part (SVG + DXF). Best effort: a part without a drawing is still a part."""
        try:
            res = await self._mcp.call(
                "freecad",
                "drawing",
                {
                    "step": info["step"], "out_dir": str(out), "name": f"{key}_drawing", "title": key, "material": str(lk.get("material", "PETG")),
                    "mass_g": float(lk.get("mass_g") or 0) or None, "features": info["recipe"].get("features") or [], "process": "print", "gdt": True,
                },
                150,
            )
            info["drawing"] = {k: res[k] for k in ("svg", "dxf", "sheet", "scale")}
        except Exception as exc:  # noqa: BLE001
            log.info("part.drawing_failed", part=key, error=str(exc)[:160])

    async def design(
        self,
        brief: str,
        actor: str,
        progress: Any = lambda _t: None,
        auto_activate: bool = True,
        ckpt: dict[str, Any] | None = None,
        save: Any = lambda: None,
    ) -> dict[str, Any]:
        """`ckpt` is the part of the work already done (plan, built parts): a restarted design reuses it."""
        ckpt = {} if ckpt is None else ckpt
        if "plan" not in ckpt:
            ckpt.update(plan=await self._race(brief, progress), out=uuid.uuid4().hex[:8], built={})
            save()
        plan = ckpt["plan"]
        early = robot_issues(plan)  # the numbers already say no (too many joints, weak actuator, tips over): do not spend minutes of CPU building its parts
        if early and not ckpt["built"]:
            self._learn.note("structure", "plan_rejected", f"{plan['name']}: " + "; ".join(early[:3]), once=True)
            raise RuntimeError("plan reddedildi, parçalar üretilmedi: " + "; ".join(early[:4]))
        name = model_name(str(plan["name"]))[:20]
        out = self._work / ckpt["out"]
        out.mkdir(parents=True, exist_ok=True)
        built: dict[str, dict[str, Any]] = ckpt["built"]
        meshes: dict[str, str] = {}
        for lk in plan["links"]:
            if lk["source"] == "designed":
                key = slug(str(lk["name"]))
                if key not in built or not (out / f"{key}.stl").exists():
                    built[key] = await self._part(lk, out, progress, body_kg=plan_mass(plan))
                    await self._draw(key, built[key], lk, out)
                    save()
                meshes[key] = f"{key}.stl"
        progress("montaj ve denetim")
        urdf = urdf_of(plan, meshes)
        try:
            summary, found, rig, _ = assemble(urdf)
        except UrdfError as exc:
            raise RuntimeError(f"URDF okunamadı: {exc}") from exc
        problems = [
            *gate(plan, built),
            *layout_issues(plan),
            *robot_issues(plan),
        ]  # a layout the critic still dislikes keeps the design a draft
        entries = await self._entries(plan, built, meshes, urdf, (summary, found, rig))
        model, draft_id = await self._store(entries, plan, name, actor, brief, problems)
        activated = False
        if not problems and auto_activate:
            await self._activate(draft_id, model)
            activated = True
            progress("denetimi geçti: simülasyon tasarımı olarak devreye alındı")
        else:
            progress(
                "taslak olarak bırakıldı: "
                + ("; ".join(problems) or "otomatik devreye alma kapalı")
            )
        if not problems and self.skills is not None:  # a design that passed the gate: its parts are worth showing again
            for lk in plan["links"]:
                info = built.get(slug(str(lk["name"])), {})
                recipe = None if info.get("quality") else info.get("recipe")
                if lk["source"] == "designed" and recipe:
                    self.skills.add(f"{name}/{lk['name']}", str(lk["role"]), recipe, "design")
        for p in problems:
            self._learn.note("structure", "generated", f"{model}: {p}", once=True)
        return {
            "model": model,
            "draft": draft_id,
            "activated": activated,
            "problems": problems,
            "pack": build_pack(plan, built, problems),
            "links": len(plan["links"]),
        }

    async def _entries(
        self,
        plan: dict[str, Any],
        built: dict[str, dict[str, Any]],
        meshes: dict[str, str],
        urdf: str,
        assembled: tuple[Any, Any, Any],
    ) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for lk in plan["links"]:
            name = slug(str(lk["name"]))
            if name not in built:
                continue
            info = built[name]
            stl = Path(info["stl"])
            mesh = await self._imp._mesh(stl, "stl", stl.parent)  # noqa: SLF001
            step_url = await self._imp._uploader.upload(Path(info["step"]), "step")  # noqa: SLF001
            if step_url:
                mesh["urls"]["step"] = step_url
            for kind in ("svg", "dxf"):  # the manufacturing drawing, when one was made
                if info.get("drawing"):
                    url = await self._imp._uploader.upload(Path(info["drawing"][kind]), kind)  # noqa: SLF001
                    if url:
                        mesh["urls"][f"drawing_{kind}"] = url
            entries.append(
                {
                    "id": f"gen_{name}",
                    "kind": "stl",
                    "name": name,
                    "file": meshes[name],
                    "branch": "",
                    "source": "NEML tasarımı",
                    "repo": "generated",
                    "license": "NEML üretimi",
                    "sha256": hashlib.sha256(stl.read_bytes()).hexdigest(),
                    **mesh,
                    "design": {
                        "role": lk["role"],
                        "material": lk.get("material"),
                        "recipe": info["recipe"],
                        "volume_mm3": info["volume_mm3"],
                    },
                }
            )
        summary, found, rig = assembled
        entries.append(
            {
                "id": "gen_urdf",
                "kind": "urdf",
                "name": slug(plan["name"]),
                "file": "robot.urdf",
                "branch": "",
                "source": "NEML tasarımı",
                "repo": "generated",
                "license": "NEML üretimi",
                "sha256": hashlib.sha256(urdf.encode()).hexdigest(),
                "urdf": summary,
                "assembly": found,
                "rig": rig,
                "unmatched": [],
            }
        )
        return entries

    async def _store(
        self, entries: list[dict[str, Any]], plan: dict[str, Any], name: str, actor: str, brief: str, findings: list[str] | None = None
    ) -> tuple[str, str]:
        runner = self._imp.runner
        async with self._sessions() as session:
            seed = await runner.active_genome()
            body = deepcopy(dict(seed["body"]))
            model = await self._imp._free_name(name)  # noqa: SLF001
            body["genome_id"] = model
            body["morphology"]["body_type"] = "imported"
            for key in ("layout", "assembly"):
                body["mechanical"].pop(key, None)
            body["mechanical"]["imports"] = entries
            body["mechanical"]["body_mass_kg"] = round(plan_mass(plan), 3)
            body["mechanical"]["generated"] = {
                "brief": brief,
                "purpose": plan["purpose"],
                "by": actor,
                "findings": (findings or [])[:8],  # the hard judges' numbers: the round table argues about the fix, not the fact
            }
            draft_id, draft_body = await runner._new_genome(
                session, {**seed, "id": None, "version": 0}, body, status="draft"
            )  # noqa: SLF001
            await session.commit()
        await runner._publish_scene(draft_id, draft_body)  # noqa: SLF001
        return model, draft_id

    async def _activate(self, genome_id: str, model: str) -> None:
        async with self._sessions() as session:
            await session.execute(
                sa.text(
                    "UPDATE genomes SET status = 'deprecated' WHERE name = :n AND status IN ('active','draft') AND id <> :id"
                ),
                {"n": model, "id": genome_id},
            )
            await session.execute(
                sa.text("UPDATE genomes SET status = 'active' WHERE id = :id"), {"id": genome_id}
            )
            await session.commit()
        log.info("generative.activated", genome=genome_id, model=model)
