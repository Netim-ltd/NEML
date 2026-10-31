# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A fixed set of parts with known volumes: how well does the model write CSG recipes?

Each case is a plain-language part (as in text-to-cad's benchmark of simple mechanical parts) with a volume
worked out by hand. A case passes when the CAD server accepts the recipe, the result is one valid solid and its
volume and bounding box are within tolerance. Run after a model change (new LLM, new prompt) to see whether
part design got better or worse; the report is kept in `bench.json`."""

from __future__ import annotations

import asyncio
import json
import math
import random
import time
import uuid
from pathlib import Path
from typing import Any

import structlog

from neml_brain.evolution.judges import recipe_issues

log = structlog.get_logger(__name__)
PI = math.pi

CASES: list[dict[str, Any]] = [
    {
        "id": "kalibrasyon_blogu",
        "prompt": "40 x 40 x 20 mm dolu dikdörtgen kalibrasyon bloğu.",
        "dims": [40, 40, 20],
        "volume": 40 * 40 * 20,
    },
    {
        "id": "flans",
        "prompt": "Çapı 80 mm, kalınlığı 10 mm yuvarlak flanş. Ortasında 30 mm çaplı delik, 60 mm çaplı daire üzerinde eşit aralıklı 4 adet 6 mm çaplı delik (hepsi tam geçişli).",
        "dims": [80, 80, 10],
        "volume": PI * 40**2 * 10 - PI * 15**2 * 10 - 4 * PI * 3**2 * 10,
    },
    {
        "id": "l_braket",
        "prompt": "L braket: 60 x 40 x 4 mm taban plakası ve tabanın bir 60 mm'lik kenarında 4 mm kalınlıkta, toplam 40 mm yüksekliğinde dik duvar (taban ile duvar birleşik). Tabanda 4.5 mm çaplı 2 adet geçişli delik.",
        "dims": [60, 40, 40],
        "volume": 60 * 40 * 4 + 60 * 4 * 36 - 2 * PI * 2.25**2 * 4,
    },
    {
        "id": "kademeli_mil",
        "prompt": "Aynı eksende üç kademeli mil: 20 mm çaplı 40 mm uzunluk, ardından 15 mm çaplı 30 mm, ardından 10 mm çaplı 20 mm (toplam 90 mm).",
        "dims": [20, 20, 90],
        "volume": PI * 10**2 * 40 + PI * 7.5**2 * 30 + PI * 5**2 * 20,
    },
    {
        "id": "elektronik_kutusu",
        "prompt": "Üstü açık elektronik kutusu: dış ölçü 80 x 60 x 30 mm, duvar ve taban kalınlığı 2 mm.",
        "dims": [80, 60, 30],
        "volume": 80 * 60 * 30 - 76 * 56 * 28,
    },
    {
        "id": "mafsal_braketi",
        "prompt": "Çatal (clevis) braket: 50 x 30 x 30 mm blok; üstten 20 mm genişliğinde (X yönünde ortada), 30 mm derinliğinde (tüm Y boyunca), 20 mm yüksekliğinde yuva açılmış. İki kulağı X yönünde delen 8 mm çaplı pim deliği (Y ortasında, taban üstünden 22 mm yükseklikte).",
        "dims": [50, 30, 30],
        "volume": 50 * 30 * 30 - 20 * 30 * 20 - 2 * 15 * PI * 4**2,
    },
    {
        "id": "kanatcikli_silindir",
        "prompt": "Soğutma kanatçıklı silindir: 30 mm çaplı, 50 mm yüksekliğinde gövde; üzerinde 44 mm çaplı, 3 mm kalınlıkta 4 adet kanatçık halkası (gövdeyle birleşik, eşit aralıklı).",
        "dims": [44, 44, 50],
        "volume": PI * 15**2 * 50 + 4 * PI * (22**2 - 15**2) * 3,
    },
    {
        "id": "yuvarlak_koseli_plaka",
        "prompt": "60 x 40 x 6 mm plaka; dört dikey köşesi 5 mm yarıçaplı yuvarlatılmış (fillet).",
        "dims": [60, 40, 6],
        "volume": 60 * 40 * 6 - 4 * (1 - PI / 4) * 5**2 * 6,
    },
    {
        "id": "merdiven",
        "prompt": "5 basamaklı düz merdiven: her basamak 30 mm geniş, 10 mm derin, birbirini izleyen basamakların yüksekliği 10, 20, 30, 40, 50 mm (hepsi tek parça, arkaya doğru yükselir).",
        "dims": [30, 50, 50],
        "volume": 30 * 10 * (10 + 20 + 30 + 40 + 50),
    },
    {
        "id": "boru",
        "prompt": "Boru parçası: dış çap 40 mm, iç çap 30 mm, boy 60 mm (içi boş, iki ucu açık).",
        "dims": [40, 40, 60],
        "volume": PI * (20**2 - 15**2) * 60,
    },
    {
        "id": "rondela",
        "prompt": "Rondela: dış çap 30 mm, ortasında 12 mm çaplı delik, kalınlık 3 mm.",
        "dims": [30, 30, 3],
        "volume": PI * (15**2 - 6**2) * 3,
    },
    {
        "id": "u_kanal",
        "prompt": "U kanal profil: 60 mm boyunda, dış kesit 30 x 20 mm, duvar kalınlığı 3 mm, üstü açık (taban ve iki yan duvar).",
        "dims": [30, 60, 20],
        "volume": 60 * (30 * 20 - 24 * 17),
    },
    {
        "id": "kure",
        "prompt": "15 mm yarıçaplı dolu küre.",
        "dims": [30, 30, 30],
        "volume": 4 / 3 * PI * 15**3,
    },
    {
        "id": "kure_bosluklu_kup",
        "prompt": "40 mm kenarlı küp; tam ortasında 20 mm çaplı küresel boşluk (içi boş, dışarıya açılmayan).",
        "dims": [40, 40, 40],
        "volume": 40**3 - 4 / 3 * PI * 10**3,
    },
    {
        "id": "yuvali_plaka",
        "prompt": "80 x 30 x 5 mm plaka; ortasında 40 x 10 mm dikdörtgen geçişli yuva (uzun kenarına paralel).",
        "dims": [80, 30, 5],
        "volume": 80 * 30 * 5 - 40 * 10 * 5,
    },
    {
        "id": "t_profil",
        "prompt": "T parça: 50 x 40 x 5 mm üst flanş plakası ve altında ortada 5 mm kalınlıkta, 40 mm uzunlukta, 25 mm yüksekliğinde dikey gövde (toplam yükseklik 30 mm, tek parça).",
        "dims": [50, 40, 30],
        "volume": 50 * 40 * 5 + 5 * 40 * 25,
    },
    {
        "id": "kademeli_blok",
        "prompt": "40 x 40 x 10 mm taban bloğu; üstünde ortalanmış 20 x 20 x 15 mm ikinci blok (tek parça).",
        "dims": [40, 40, 25],
        "volume": 40 * 40 * 10 + 20 * 20 * 15,
    },
    {
        "id": "capraz_delikli_kup",
        "prompt": "30 mm kenarlı küp; bir yüzden karşısına tam geçişli, 10 mm çaplı, yüzeye dik ve ortalı delik.",
        "dims": [30, 30, 30],
        "volume": 30**3 - PI * 5**2 * 30,
    },
]
PARALLEL = 2
VOLUME_TOL = 0.06
BOX_TOL = 0.06


def score(case: dict[str, Any], built: dict[str, Any]) -> dict[str, Any]:
    """Volume error and bounding-box error of one built part against the case."""
    x0, y0, z0, x1, y1, z1 = built["bbox"]
    got = sorted([x1 - x0, y1 - y0, z1 - z0])
    want = sorted(case["dims"])
    box_err = max(abs(g - w) / w for g, w in zip(got, want, strict=True))
    vol_err = abs(built["volume_mm3"] - case["volume"]) / case["volume"]
    flaws = recipe_issues(built["recipe"]) if built.get("recipe") else []  # right numbers from a nonsense recipe do not count
    return {
        "volume_err": round(vol_err, 3),
        "box_err": round(box_err, 3),
        "passed": vol_err <= VOLUME_TOL and box_err <= BOX_TOL and not flaws,
        **({"error": "tarif anlamsız: " + "; ".join(flaws)[:140]} if flaws else {}),
    }


class CadBench:
    def __init__(self, generator: Any, work: Path, root: Path) -> None:
        self._gen, self._work, self._path = generator, work, root / "bench.json"
        self._task: asyncio.Task[Any] | None = None

    def report(self) -> dict[str, Any]:
        try:
            return dict(json.loads(self._path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return {}

    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> dict[str, Any]:
        run = {"id": uuid.uuid4().hex[:8], "state": "running", "at": time.time(), "cases": [], "total": len(CASES)}
        self._write(run)
        self._task = asyncio.create_task(self._run(run, None, True))
        return run

    def _write(self, run: dict[str, Any], keep: bool = True) -> None:
        if not keep:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")

    async def _run(self, run: dict[str, Any], rules: list[str] | None, keep: bool, only: set[str] | None = None) -> None:
        out = self._work / f"bench_{run['id']}"
        out.mkdir(parents=True, exist_ok=True)
        gate = asyncio.Semaphore(PARALLEL)  # the model server has this many slots

        async def one(case: dict[str, Any]) -> None:
            async with gate:
                started = time.time()
                lk = {"name": case["id"], "role": case["prompt"], "dims_mm": case["dims"], "material": "PETG", "case": case["id"]}
                try:
                    built = await self._gen._part(lk, out, lambda _t: None, rules)  # noqa: SLF001 - the same path a design takes
                    row = {"id": case["id"], **score(case, built)}
                    skills = getattr(self._gen, "skills", None)
                    if row["passed"] and skills is not None and keep:  # a checked recipe is worth showing for similar parts
                        skills.add(case["id"], case["prompt"], built["recipe"], "bench")
                except Exception as exc:  # noqa: BLE001 - a case the model cannot do is a result, not a crash
                    row = {"id": case["id"], "passed": False, "error": str(exc)[:160]}
                row["seconds"] = round(time.time() - started)
                run["cases"] = [*run["cases"], row]
                self._write(run, keep)

        await asyncio.gather(*(one(c) for c in CASES if only is None or c["id"] in only))
        order = {c["id"]: i for i, c in enumerate(CASES)}
        run["cases"] = sorted(run["cases"], key=lambda r: order[r["id"]])
        run.update(state="done", passed=sum(1 for c in run["cases"] if c["passed"]))
        self._write(run, keep)
        log.info("bench.done", passed=run["passed"], total=run["total"])

    async def trial(self, rules: list[str], only: set[str] | None = None) -> dict[str, Any]:
        """A run (all cases, or only `only`) with other recipe rules; the report on disk is left alone."""
        run = {"id": uuid.uuid4().hex[:8], "state": "running", "at": time.time(), "cases": [], "total": len(CASES)}
        await self._run(run, rules, False, only)
        return run


RULE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["action", "index", "rule"],
    "properties": {
        "action": {"enum": ["add", "replace", "remove"]},
        "index": {"type": "integer", "minimum": 0, "maximum": 5},
        "rule": {"type": "string", "maxLength": 160},
        "note": {"type": "string", "maxLength": 12},
    },
}
RULE_PROMPT = (
    "CSG tarifi yazan bir modelin ölçümde başarısız olduğu parçalar:\n{failed}\n"
    "Şu an geçerli kurallar (sıra numarasıyla): {rules}\n"
    "Daha önce denenip ATILAN kurallar (tekrarlama): {tried}\n"
    "Diğer iyi kural setlerinden ilham: {inspired}\n"
    "Araştırma notları (kaynaklı ama henüz denenmemiş; birini genel bir kurala çevirirsen 'note' alanına kimliğini yaz, çevirmiyorsan boş bırak): {research}\n"
    "Kural setini iyileştir: action=add (yeni kural), replace (index'teki kuralı değiştir) ya da remove (index'teki kuralı kaldır; rule boş olabilir). "
    "Kural tek cümle ve genel olsun (bu parçalara özel olmasın). Birimler mm; tarif yalnızca box/cyl/sphere, cut/fuse ve round kullanır."
)
MAX_RULES = 6
PROPOSALS = 3  # asks per round before giving up on a new rule
ARCHIVE = 8  # rule sets kept (the best ones), as in OpenEvolve's program database


def apply(rules: list[str], change: dict[str, Any]) -> list[str]:
    """The rule set after one proposed change (add / replace / remove); an impossible change leaves it as it was."""
    rule, i, out = str(change["rule"]).strip(), int(change["index"]), list(rules)
    if change["action"] == "remove" and i < len(out):
        del out[i]
    elif change["action"] == "replace" and i < len(out) and rule:
        out[i] = rule
    elif change["action"] != "remove" and rule and rule not in out:  # nothing to replace at that index: it is a new rule
        out = [*out, rule][-MAX_RULES:]
    return out


class Evolver:
    """The lab improves how it asks for parts, in the manner of OpenEvolve: an archive of rule sets with their benchmark scores,
    a parent drawn from it (mostly the best, sometimes another), a proposed change shown the failures, the rejected tries and the
    other good sets, a cascade evaluation (first only the cases the parent failed, the whole benchmark only if one of them now passes),
    and selection by score. Rules are plain sentences added to the part prompt, never code."""

    def __init__(self, bench: CadBench, generator: Any, llm: Any, root: Path, notes: Any = None) -> None:
        self._bench, self._gen, self._llm, self._path = bench, generator, llm, root / "evolve.json"
        self._notes = notes  # KnowledgeBase: researched claims are tried as rules and judged by the benchmark
        self._task: asyncio.Task[Any] | None = None
        self._gen.rules = list(self.state().get("rules", []))

    def state(self) -> dict[str, Any]:
        try:
            return dict(json.loads(self._path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return {}

    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> dict[str, Any]:
        self._task = asyncio.create_task(self.step())
        return {"state": "running"}

    async def step(self) -> dict[str, Any] | None:
        """One round. Skipped while a design or a measurement runs."""
        if self._gen.busy() or self._bench.busy():
            return None
        st = self.state()
        if st.get("best") is not None and {c["id"] for c in st.get("cases", [])} != {c["id"] for c in CASES}:
            st = {"rules": st.get("rules", []), "history": st.get("history", [])[-8:]}  # the benchmark changed: scores are not comparable, measure again
        if st.get("best") is None:
            done = self._bench.report()
            base = done if done.get("state") == "done" and len(done.get("cases", [])) == len(CASES) and not st.get("rules") else await self._bench.trial(list(st.get("rules", [])))
            n = sum(1 for c in base["cases"] if c["passed"])
            st.update(rules=list(st.get("rules", [])), best=n, cases=base["cases"], history=st.get("history", []), archive=[{"rules": list(st.get("rules", [])), "passed": n, "cases": base["cases"]}])
            self._save(st)
        archive: list[dict[str, Any]] = st["archive"]
        parent = archive[0] if random.random() < 0.7 or len(archive) < 2 else random.choice(archive[1:])  # noqa: S311 - exploration, not security
        failed = [c for c in parent["cases"] if not c["passed"]]
        if not failed:
            return st
        focus = random.choice(failed)  # noqa: S311 - one failure per round gives the proposals something different to aim at
        listing = f"{focus['id']}: {focus.get('error') or 'hacim hatası %' + format(focus.get('volume_err', 0) * 100, '.0f')}"
        also = "; ".join(c["id"] for c in failed if c is not focus) or "(yok)"
        tried = "; ".join(h["rule"] for h in st["history"][-12:] if not h["kept"]) or "(yok)"
        inspired = " | ".join("; ".join(a["rules"]) for a in archive[:3] if a is not parent and a["rules"]) or "(yok)"
        seen = {h["rule"].split(": ", 1)[-1].strip().lower() for h in st["history"]}
        claims = {n["id"]: n for n in (self._notes.untested("cad") if self._notes else [])}
        research = " | ".join(f"[{i}] {n['rule'][:150]}" for i, n in claims.items()) or "(yok)"
        said: dict[str, Any] = {"action": "add", "index": 0, "rule": ""}
        candidate = parent["rules"]
        for attempt in range(PROPOSALS):  # a rule that was already tried is not tried again: ask once more, hotter, with it named
            said = await self._llm.fill(
                RULE_PROMPT.format(failed=listing + f" (diğer başarısızlar: {also})", rules="; ".join(f"{i}: {r}" for i, r in enumerate(parent["rules"])) or "(yok)", tried=tried, inspired=inspired, research=research),
                RULE_SCHEMA,
                profile="param_skill",
                max_tokens=250,
                **({"temperature": 0.6 + 0.2 * attempt} if attempt else {}),
            )
            rule = said["rule"].strip().lower()
            if rule and rule in seen:
                tried += f"; {said['rule'].strip()}"
                continue
            candidate = apply(parent["rules"], said)
            break
        entry = {"at": time.time(), "rule": f"{said['action']}: {said['rule']}"[:200], "before": parent["passed"], "passed": parent["passed"], "kept": False, "stage": 0}
        note = claims.get(str(said.get("note", "")))
        if note:
            entry["note"] = note["id"]
        if candidate != parent["rules"]:
            cheap = await self._bench.trial(candidate, {c["id"] for c in failed})  # stage 1: only what the parent failed
            gained = sum(1 for c in cheap["cases"] if c["passed"])
            entry.update(stage=1, passed=parent["passed"] + gained)
            if gained:  # stage 2: the whole benchmark, so nothing that worked got broken
                full = await self._bench.trial(candidate)
                passed = sum(1 for c in full["cases"] if c["passed"])
                entry.update(stage=2, passed=passed)
                if passed > parent["passed"]:
                    entry["kept"] = True
                    archive.append({"rules": candidate, "passed": passed, "cases": full["cases"]})
                    archive.sort(key=lambda a: -a["passed"])
                    st["archive"] = archive[:ARCHIVE]
                    best = st["archive"][0]
                    st.update(rules=best["rules"], best=best["passed"], cases=best["cases"])
                    self._gen.rules = best["rules"]
        if note and candidate != parent["rules"]:  # the claim was tried: the benchmark decides whether it stays in the notes
            entry["note_status"] = self._notes.judge(note["id"], entry["kept"], {"experiment": "cad_rule", "before": parent["passed"], "after": entry["passed"], "stage": entry["stage"], "at": time.time()})
        st["history"] = [*st["history"][-19:], entry]
        self._save(st)
        log.info("evolve.step", change=entry["rule"][:80], stage=entry["stage"], kept=entry["kept"])
        return st

    def _save(self, st: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
