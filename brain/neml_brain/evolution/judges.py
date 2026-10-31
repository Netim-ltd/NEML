# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hard judges: plain checks with numbers, not opinions. A recipe or a robot plan that fails one goes back to the model with
the measured reason; a recipe that passes a benchmark case only counts (and is only kept as a skill) when it is also sensible."""

from __future__ import annotations

from typing import Any


def recipe_issues(recipe: dict[str, Any]) -> list[str]:
    """Why a recipe that the CAD server accepted is still not a sensible part (empty = fine)."""
    solids = [s for s in recipe.get("solids") or [] if isinstance(s, dict)]
    steps = [s for s in recipe.get("steps") or [] if isinstance(s, dict)]
    out: list[str] = []
    for st in steps:
        if st.get("a") == st.get("b"):
            out.append(f"adım {st.get('out')}: {st.get('a')} kendisiyle {st.get('op')} edilemez")
    made = {st.get("out"): st for st in steps}
    copies = {s["id"]: s["of"] for s in solids if s.get("of")}  # an array, circle or mirror is made of an earlier solid
    needed: set[str] = set()
    todo = [recipe.get("result")]
    while todo:
        cur = todo.pop()
        if cur in needed:
            continue
        needed.add(cur)
        if cur in made:
            todo += [made[cur].get("a"), made[cur].get("b")]
        elif cur in copies:
            todo.append(copies[cur])
    unused = [s["id"] for s in solids if s.get("id") not in needed]
    if unused:
        out.append(f"şu katılar sonuca hiç katılmıyor: {', '.join(map(str, unused[:5]))}")
    bad = [s["id"] for s in solids if not str(s.get("id", "")).isascii() or not str(s.get("id", "")).replace("_", "").isalnum()]
    if bad:
        out.append(f"geçersiz kat adı: {', '.join(map(str, bad[:3]))}")
    return out


MAX_ARMS = 20  # more driven joints than this on one robot is the model marking everything as moving (a hexapod has 18)
MIN_SECTION = 6.0  # mm, cross-section of a slender printed bar
WHEEL = ("tekerlek", "wheel", "teker")
SAFETY = 2.0  # a joint's actuator must give twice the torque the load needs
MIN_TIP = 0.5  # half the narrower footprint side over the height of the centre of mass


def _loads(plan: dict[str, Any]) -> tuple[list[str], dict[str, list[dict[str, Any]]], list[tuple[str, float]], list[tuple[str, float]]]:
    """Catalog complaints, the bought parts by kind, and the torque each driven wheel / arm joint needs (kg*cm)."""
    from neml_brain.evolution.catalog import CATALOG, OTHER
    from neml_brain.evolution.generative import layout, slug

    links = plan["links"]
    out: list[str] = []
    kinds: dict[str, list[dict[str, Any]]] = {}
    for lk in links:
        if lk["source"] != "bought":
            continue
        part = CATALOG.get(str(lk.get("part", "")))
        if part is None:
            tag = "katalogda yok" if lk.get("part") == OTHER else "part alanı boş/yanlış"
            out.append(f"{lk['name']}: satın alınan parça {tag}; katalogdaki bir parçayı seç")
        else:
            kinds.setdefault(part["kind"], []).append(part)
    centre, size, parent = layout(plan)
    mass = {slug(str(lk["name"])): float(lk["mass_g"]) / 1000 for lk in links}
    children: dict[str, list[str]] = {}
    for n, up in parent.items():
        children.setdefault(up, []).append(n)

    def subtree(n: str) -> list[str]:
        return [n, *(m for c in children.get(n, []) for m in subtree(c))]

    total = sum(mass.values())
    wheels, arms = [], []
    for lk in links:
        if lk["joint"]["type"] != "revolute":
            continue
        n = slug(str(lk["name"]))
        group = subtree(n)
        m = sum(mass[g] for g in group)
        com = [sum(mass[g] * centre[g][k] for g in group) / m for k in range(3)]
        lever_cm = max(sum((com[k] - centre[n][k]) ** 2 for k in range(3)) ** 0.5, max(size[n]) / 2, 5.0) / 10  # a link turns about its end: at least half its length
        if any(w in (n + " " + str(lk["role"])).lower() for w in WHEEL):
            radius_cm = max(size[n]) / 20
            wheels.append((n, total * radius_cm * 0.25))
        else:
            arms.append((n, m * lever_cm))
    if wheels:  # the load is shared by the driven wheels
        wheels = [(n, need / len(wheels)) for n, need in wheels]
    return out, kinds, wheels, arms


def robot_issues(plan: dict[str, Any]) -> list[str]:
    """What is wrong with a robot plan by the numbers (empty = nothing found): parts must come from the catalog, every moving joint
    needs an actuator that can carry its load with a safety factor, a powered robot needs a controller, a battery and a stop switch,
    and it must not tip over. The torque pairing is a heuristic (strongest actuator to the hardest joint).
    # ponytail: static torque (mass x lever); dynamics, gear backlash and stall current are not modelled."""
    out, kinds, wheels, arms = _loads(plan)
    from neml_brain.evolution.generative import tip_margin

    motors = sorted((p["torque_kgcm"] for p in kinds.get("dc_motor", [])), reverse=True)
    servos = sorted((p["torque_kgcm"] for p in kinds.get("servo", [])), reverse=True)
    for label, joints, pool in (("tekerlek", wheels, motors), ("eklem", arms, servos)):
        if len(joints) > len(pool):
            out.append(f"{len(joints)} {label} döner ama yalnızca {len(pool)} uygun {'DC motor' if label == 'tekerlek' else 'servo'} var")
        for (n, need), have in zip(sorted(joints, key=lambda j: -j[1]), pool, strict=False):
            if have < SAFETY * need:
                out.append(f"{n}: gereken tork {need:.2f} kg*cm (x{SAFETY:g} pay), seçilen aktüatör {have:g} kg*cm; daha güçlü parça ya da daha kısa kol")
    if len(arms) > MAX_ARMS:
        out.append(f"{len(arms)} döner kol eklemi var (en çok {MAX_ARMS}): yalnızca gerçekten hareket eden eklemler revolute olsun, gövde ve sabit parçaların eklemi fixed olsun")
    if wheels or arms:
        for need, label in (("board", "kontrolcü kartı"), ("battery", "batarya"), ("switch", "acil durdurma/ana şalter")):
            if not kinds.get(need):
                out.append(f"hareketli robotta {label} yok")
        if not any(p["id"] == "estop_22mm" for p in kinds.get("switch", [])):
            out.append("acil durdurma düğmesi (estop_22mm) eklenmeli")
    tip = round(tip_margin(plan), 2)
    if tip < MIN_TIP:
        out.append(f"devrilme payı {tip} (en az {MIN_TIP}): ağırlık merkezi çok yüksek ya da taban dar")
    return out


def tidy(recipe: dict[str, Any]) -> dict[str, Any]:
    """Mend harmless noise instead of rejecting it: a step that combines a solid with itself is a no-op (later uses of its output
    point at the solid), and solids that never reach the result are dropped. Geometry that matters is never touched."""
    solids = [dict(s) for s in recipe.get("solids") or [] if isinstance(s, dict)]
    alias: dict[str, str] = {}

    def at(name: Any) -> Any:
        while name in alias:
            name = alias[name]
        return name

    steps = []
    for st in (s for s in recipe.get("steps") or [] if isinstance(s, dict)):
        a, b = at(st.get("a")), at(st.get("b"))
        if a == b:
            alias[st.get("out")] = a
            continue
        steps.append({**st, "a": a, "b": b})
    result = at(recipe.get("result"))
    made = {st["out"]: st for st in steps}
    copies = {s["id"]: s["of"] for s in solids if s.get("of")}
    needed: set[Any] = set()
    todo = [result]
    while todo:
        cur = todo.pop()
        if cur not in needed:
            needed.add(cur)
            if cur in made:
                todo += [made[cur]["a"], made[cur]["b"]]
            elif cur in copies:
                todo.append(copies[cur])
    kept_steps = [st for st in steps if st["out"] in needed]
    return {**recipe, "solids": [s for s in solids if s.get("id") in needed] or solids, "steps": kept_steps, "result": result}


def equip(plan: dict[str, Any]) -> dict[str, Any]:
    """Complete a moving robot from the catalog: the controller, battery and stop switch it lacks, and for every driven joint without
    an actuator the lightest catalog motor/servo that carries the load with the safety factor. The model keeps designing the body;
    the bought essentials are not left to its memory. Added links sit on the root and the layout solver moves them apart.
    # ponytail: first-fit by weight, no voltage or current budget; the owner still checks the bill of materials."""
    from copy import deepcopy

    from neml_brain.evolution.catalog import CATALOG

    out = deepcopy(plan)
    for lk in out["links"]:  # a slender printed bar thinner than MIN_SECTION fails the beam check whatever the recipe says
        d = [float(v) for v in lk["dims_mm"]]
        if lk["source"] == "designed" and max(d) >= 4 * min(d):
            lk["dims_mm"] = [max(v, MIN_SECTION) if v < max(d) else v for v in d]
    _, kinds, wheels, arms = _loads(out)
    if not (wheels or arms):
        return out
    have = {k: len(v) for k, v in kinds.items()}
    want: list[str] = []
    for kind, joints in (("dc_motor", wheels), ("servo", arms if len(arms) <= MAX_ARMS else [])):  # too many arm joints: the judge sends it back instead
        held = sorted((p["torque_kgcm"] for p in kinds.get(kind, [])), reverse=True)
        for i, (_, need) in enumerate(sorted(joints, key=lambda j: -j[1])):
            if i < len(held) and held[i] >= SAFETY * need:
                continue
            fits = [p for p in CATALOG.values() if p["kind"] == kind and p["torque_kgcm"] >= SAFETY * need]
            pick = min(fits or [p for p in CATALOG.values() if p["kind"] == kind], key=lambda p: (p["torque_kgcm"] < SAFETY * need, p["mass_g"]))
            want.append(pick["id"])
            if i < len(held):
                held[i] = 0  # the weaker one it replaces stays, the new one is added
    motors = sum(1 for pid in want if CATALOG[pid]["kind"] == "dc_motor") + have.get("dc_motor", 0)
    servos = sum(1 for pid in want if CATALOG[pid]["kind"] == "servo") + have.get("servo", 0)
    drivers = sum(p.get("channels", 0) for p in kinds.get("driver", []))  # a driver board is added only when the robot has none for its actuators
    if motors and not any(p["id"] == "tb6612" for p in kinds.get("driver", [])):
        want += ["tb6612"] * -(-motors // 2)
    if servos > 4 and drivers < servos:
        want.append("pca9685")
    for kind, pid in (("board", "esp32_devkit"), ("battery", "lipo_3s_2200"), ("switch", "estop_22mm")):
        if not have.get(kind):
            want.append(pid)
    if kinds.get("switch") and not any(p["id"] == "estop_22mm" for p in kinds["switch"]) and "estop_22mm" not in want:
        want.append("estop_22mm")
    root = out["links"][0]
    rl, rw, rh = (float(v) for v in root["dims_mm"])
    taken = {str(lk["name"]) for lk in out["links"]}
    x, y, z, row_w, layer_h = -rl / 2, -rw / 2, rh / 2, 0.0, 0.0  # shelf packing on the root's top face, then the next layer up
    for i, pid in enumerate(want):
        part = CATALOG[pid]
        pl, pw, ph = (float(v) for v in part["dims_mm"])
        if x + pl > rl / 2 and x > -rl / 2:
            x, y, row_w = -rl / 2, y + row_w, 0.0
        if y + pw > rw / 2 and y > -rw / 2:
            x, y, row_w, z, layer_h = -rl / 2, -rw / 2, 0.0, z + layer_h, 0.0
        name = f"{pid}_{i + 1}"
        while name in taken:
            name += "_"
        taken.add(name)
        out["links"].append(
            {
                "name": name,
                "parent": root["name"],
                "role": f"{part['name']} (otomatik tamamlandı)",
                "source": "bought",
                "part": pid,
                "dims_mm": [pl, pw, ph],
                "mass_g": part["mass_g"],
                "joint": {"type": "fixed", "x": x + pl / 2, "y": y + pw / 2, "z": z + ph / 2, "axis": "z"},
            }
        )
        x, row_w, layer_h = x + pl, max(row_w, pw), max(layer_h, ph)
    return out


def without_cuts(recipe: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Recipes that differ by one cut step left out (the last first), for a recipe whose result the CAD server called empty/invalid:
    a cut that swallows its whole body is the usual cause. The step's output becomes its first operand; later steps follow.
    # ponytail: one cut at a time; two bad cuts need the model's own retry."""
    steps = [s for s in recipe.get("steps") or [] if isinstance(s, dict)]
    found = []
    for i in reversed(range(len(steps))):
        if steps[i].get("op") != "cut":
            continue
        gone, rest = steps[i], steps[:i] + steps[i + 1 :]
        sub = {gone.get("out"): gone.get("a")}
        rest = [{**s, "a": sub.get(s.get("a"), s.get("a")), "b": sub.get(s.get("b"), s.get("b"))} for s in rest]
        result = sub.get(recipe.get("result"), recipe.get("result"))
        found.append((f"kesim {gone.get('b')} atlandı (sonuç boş çıkıyordu)", tidy({**recipe, "steps": rest, "result": result})))
    return found


def thickened(recipe: dict[str, Any], bbox: list[float], section: float) -> dict[str, Any]:
    """The recipe with a box fused around its centre so every side but the longest is at least `section` mm: a slender bar the model
    keeps drawing thin is made sturdy by the lab itself. # ponytail: a plain box, not shaped to the part; the owner sees the mass."""
    dims = [h - lo for lo, h in zip(bbox[:3], bbox[3:], strict=True)]
    size = [max(d, section) if d < max(dims) else d for d in dims]
    at = [(lo + h) / 2 - s / 2 for lo, h, s in zip(bbox[:3], bbox[3:], size, strict=True)]
    return {
        **recipe,
        "solids": [*recipe["solids"], {"id": "sturdy", "t": "box", "at": at, "size": size}],
        "steps": [*recipe["steps"], {"op": "fuse", "a": recipe["result"], "b": "sturdy", "out": "sturdy_part"}],
        "result": "sturdy_part",
    }


def softer_rounds(recipe: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Recipes whose edge rounding is smaller (half, a quarter) and then left out, for a round the CAD server said does not fit.
    A rounding is decoration; the part without it is still the part."""
    rd = recipe.get("round")
    if not isinstance(rd, dict):
        return []
    found = [(f"yuvarlama r={rd.get('r')} sığmadı; r={float(rd.get('r', 0)) * k:g} kullanıldı", {**recipe, "round": {**rd, "r": float(rd.get("r", 0)) * k}}) for k in (0.5, 0.25)]
    found.append((f"yuvarlama r={rd.get('r')} sığmadı; yuvarlama atlandı", {k: v for k, v in recipe.items() if k != "round"}))
    return found
