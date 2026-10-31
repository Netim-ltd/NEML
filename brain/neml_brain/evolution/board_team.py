# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Boards designed by a team of agents, with no board templates.

The team (each member is one role of the language model with its own task and its own check):

  architect   describes the circuit as data (parts, pins, nets, placement hints) from the brief;
  bom picker  chooses a part number and supplier for every line, from the catalog when it knows the part;
  sourcing    looks every active part up at Turkish shops (Robotistan, Direnc.net, ...) through the fetch
              server; a price or a stock claim only counts when it quotes the shop's own page; a line that
              cannot be bought in Turkey goes back to the picker for a substitute;
  router      builds the board (the KiCad MCP draws, places and routes it) and then makes sure the tracks are
              right: KiCad's DRC and the router's own unrouted list are read, parts are moved and the board is
              routed again until it is clean or the rounds run out;
  reviewer    reads the finished design as a critic (power, polarity, protection, what to measure first).

Their messages are kept as the team's conversation. Nothing here orders or manufactures a board: SPEC 13.2
keeps a human review between a generated design and a PCB order.
"""

from __future__ import annotations

import asyncio
import copy
import csv
import io
import json
import re
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import structlog

from neml_brain.llm.schemas import ELEC_PARAM_SCHEMA

log = structlog.get_logger(__name__)

MAX_ROUNDS = 4
MAX_RESUMES = 4  # a board that keeps dying with the process is given up
MAX_ATTEMPTS = 3
SHOPS = {
    "Robotistan": "https://www.robotistan.com/arama?q={q}",
    "Direnc.net": "https://www.direnc.net/arama?q={q}",
}
KIND_TR = {
    "R": "direnç",
    "C": "kondansatör",
    "L": "bobin",
    "D": "diyot",
    "LED": "led",
    "IC": "entegre",
    "CONN": "konnektör",
    "MOD": "modül",
    "SW": "buton",
    "Q": "transistör",
    "F": "sigorta",
}
GENERIC = (
    "R",
    "C",
    "L",
    "LED",
    "D",
    "F",
    "SW",
)  # standard parts every Turkish electronics shop stocks

_SMALL = copy.deepcopy(ELEC_PARAM_SCHEMA)
del _SMALL["properties"]["limits"]  # the SPEC 13.1 scope is the server's to enforce; the model is not asked to restate it
_SMALL["properties"]["parts"]["maxItems"] = (
    16  # a model at CPU speed writes small boards well, big ones badly
)
ARCHITECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["board_name", "purpose", "circuit"],
    "properties": {
        "board_name": {"type": "string", "pattern": "^[a-z][a-z0-9_]{1,40}$"},
        "purpose": {"type": "string", "maxLength": 200},
        "circuit": _SMALL,
    },
}
PICK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["lines"],
    "properties": {
        "lines": {
            "type": "array",
            "maxItems": 60,
            "items": {
                "type": "object",
                "required": ["ref", "part_number", "supplier"],
                "properties": {
                    "ref": {"type": "string", "maxLength": 6},
                    "part_number": {"type": "string", "maxLength": 40},
                    "supplier": {"enum": ["Robotistan", "Direnc.net", "LCSC", "Mouser", "genel"]},
                },
            },
        }
    },
}
FIND_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["found", "stock", "price_try", "url", "quote"],
    "properties": {
        "found": {"type": "boolean"},
        "stock": {"enum": ["stokta", "yok", "belirsiz"]},
        "price_try": {"type": "number", "minimum": 0, "maximum": 100000},
        "url": {"type": "string", "maxLength": 200},
        "quote": {"type": "string", "maxLength": 200},
    },
}
FIX_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["diagnosis", "moves", "track_mm", "width_mm", "height_mm"],
    "properties": {
        "diagnosis": {"type": "string", "maxLength": 240},
        "moves": {
            "type": "array",
            "maxItems": 12,
            "items": {
                "type": "object",
                "required": ["ref", "x", "y"],
                "properties": {
                    "ref": {"type": "string", "maxLength": 6},
                    "x": {"type": "number", "minimum": 0, "maximum": 400},
                    "y": {"type": "number", "minimum": 0, "maximum": 400},
                },
            },
        },
        "track_mm": {"type": "number", "minimum": 0.15, "maximum": 1.0},
        "width_mm": {"type": "number", "minimum": 10, "maximum": 400},
        "height_mm": {"type": "number", "minimum": 10, "maximum": 400},
    },
}
REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["verdict", "risks", "verify_first"],
    "properties": {
        "verdict": {"enum": ["hazır", "riskli", "yeniden tasarlanmalı"]},
        "risks": {"type": "array", "maxItems": 5, "items": {"type": "string", "maxLength": 200}},
        "verify_first": {"type": "string", "maxLength": 200},
    },
}

VARIANT_HINTS = [
    "",
    "\nBu kez farklı bir yaklaşım dene: en az parçalı, en basit devre.",
    "\nBu kez farklı bir yaklaşım dene: önce güç ağacını (giriş, regülatör, yükler) çiz; her netin tek kaynağı olsun.",
]
ARCHITECT_PROMPT = (
    "Bir robot için elektronik kart tasarla: {brief}\n"
    "Kartı veri olarak yaz: parts listesi (ref örn. U1, R2; value; kind: R C L D LED IC CONN MOD SW Q F; "
    "package: 0603 0805 1206 2512 THT; pins = her biri [pin numarası, pin adı, elektriksel tür, net adı]). "
    "Elektriksel türler: input output bidirectional passive power_in power_out unspecified. Aynı net adını taşıyan pinler birbirine bağlıdır; "
    "toprak 'GND'. Kurallar: 2 katman, en küçük paket 0603, 10 A ve 48 V altı, 10 MHz altı dijital; sensörlü her entegrenin güç pinine bir 100n "
    "kondansatör koy (kondansatörün decouples alanı o entegrenin ref'i, entegrenin needs_decoupling alanı o güç neti). "
    "Toprak (GND) yalnızca bir net adıdır: GND için ayrı parça ekleme, birden çok pin aynı GND netine bağlanır. Her pinin kendi numarası olsun (1, 2, 3, ...). "
    "Bir netin en çok bir çıkışı olsun (output ya da power_out); regülatör çıkışı power_out, onu kullanan entegre ve konnektör pinleri power_in, pasifler passive, "
    "güç girişi konnektörü power_out. Kartı küçük tut: en çok 16 parça; JSON'u boşluksuz, tek satırda yaz. SMD pasif parçalar tam iki pinlidir; entegre, konnektör ve modüller çok pinli olabilir. Yerleşim ipucu (placement) isteğe bağlı: ref -> [x, y] mm.\n"
    "Bilinen notlar:\n{notes}{problem}"
)
PICK_PROMPT = (
    "Bu kartın malzeme listesini seç. Her ref için bir parça numarası ve tedarikçi ver. Türkiye'den temin edilebilen ürünleri tercih et "
    "(Robotistan, Direnc.net); pasifler için 'değer_paket' yeterli (örn. 10k_0603, tedarikçi genel). "
    "Bilinen ürünler: {catalog}\nParçalar:\n{parts}{problem}"
)
FIND_PROMPT = (
    "Aşağıdaki mağaza arama sayfasında '{query}' ürününün satıldığını gösteren bir satır var mı? Varsa fiyatı (TL), stok durumunu, ürün bağlantısını ve "
    "sayfadan BİREBİR kopyaladığın tek bir cümleyi (quote) yaz; yoksa found=false."
)
FIX_PROMPT = (
    "Sen kartın yönlendirme (routing) ajanısın. Kart {w:.0f}x{h:.0f} mm, iz kalınlığı {track} mm. Sorunlar: {problems}\n"
    "Parçaların şu anki merkezleri (mm): {places}\nBağlantısı çizilemeyen net'lerin parçalarını birbirine yaklaştır, yolları açacak şekilde diğer parçaları kaydır, "
    "gerekirse kartı büyüt veya izi inceltip (en az 0.15) yeniden dene. Parçalar kart dışına taşmasın ve birbirinin üstüne binmesin. "
    "moves içinde yalnız yerini değiştireceğin parçaları ver."
)
REVIEW_PROMPT = (
    "Bir eleştirmen elektronik mühendisi olarak şu kartı incele: {summary}\n"
    "Güç hatları, kutuplama, koruma, çekilen akım ve ilk önce neyin ölçüleceği hakkında hüküm (hazır/riskli/yeniden tasarlanmalı), en çok 5 risk ve ilk doğrulama adımını yaz."
)


class Rejected(Exception):
    """The request is understood but not possible."""


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def bom_lines(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One line per distinct part (value, package, part number): its refs and quantity."""
    lines: dict[tuple[str, str, str], dict[str, Any]] = {}
    for p in parts:
        key = (
            str(p.get("part_number") or f"{p['value']}_{p['package']}"),
            str(p["kind"]),
            str(p["package"]),
        )
        line = lines.setdefault(
            key,
            {
                "part_number": key[0],
                "kind": key[1],
                "package": key[2],
                "value": p["value"],
                "refs": [],
                "supplier": p.get("supplier", "genel"),
            },
        )
        line["refs"].append(p["ref"])
    return [{**line, "qty": len(line["refs"])} for line in lines.values()]


def catalog_hint() -> str:
    try:
        import yaml

        from neml_brain.paths import REPO_ROOT

        data = yaml.safe_load(
            (REPO_ROOT / "hardware" / "catalog" / "parts.yaml").read_text(encoding="utf-8")
        )
        return "; ".join(f"{k}: {v['title']}" for k, v in data["parts"].items())[:600]
    except Exception:  # noqa: BLE001 - the picker works without the hint
        return "(yok)"


class BoardTeam:
    def __init__(
        self, mcp: Any, uploader: Any, llm: Any, learn: Any, work: Path, notes: Any = None
    ) -> None:
        self._mcp, self._uploader, self._llm, self._learn, self._notes = (
            mcp,
            uploader,
            llm,
            learn,
            notes,
        )
        self._work = work
        self._jobs = work / "jobs.json"
        self._running: set[asyncio.Task[Any]] = set()
        self.variants = 1  # circuits raced per board (main.py raises it)

    # ------------------------------------------------------------- jobs
    def jobs(self) -> list[dict[str, Any]]:
        try:
            return list(json.loads(self._jobs.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return []

    def _save(self, job: dict[str, Any]) -> None:
        jobs = [j for j in self.jobs() if j["id"] != job["id"]] + [job]
        self._work.mkdir(parents=True, exist_ok=True)
        self._jobs.write_text(json.dumps(jobs[-30:], ensure_ascii=False), encoding="utf-8")

    def busy(self) -> bool:
        return any(
            j["state"] == "running" and time.time() - j["at"] < 3 * 3600 for j in self.jobs()
        )

    def start(self, brief: str, actor: str) -> dict[str, Any]:
        job = {
            "id": uuid.uuid4().hex[:8],
            "brief": brief[:400],
            "actor": actor,
            "state": "running",
            "talk": [],
            "at": time.time(),
            "ckpt": {},
        }
        self._save(job)
        self._launch(job)
        return job

    def _launch(self, job: dict[str, Any]) -> None:
        task = asyncio.create_task(self._run(job))
        self._running.add(task)
        task.add_done_callback(self._running.discard)

    def resume(self) -> int:
        """After a restart: boards that were being designed go on from their last checkpoint (circuit, parts, sourcing)."""
        n = 0
        for job in self.jobs():
            if job["state"] != "running":
                continue
            if job.get("resumes", 0) >= MAX_RESUMES:
                job.update(state="failed", error="çok kez yeniden başlatıldı")
                self._save(job)
                continue
            job["resumes"] = job.get("resumes", 0) + 1
            job["talk"] = [
                *job["talk"][-60:],
                {"agent": "sistem", "text": "yeniden başlatma sonrası kaldığı yerden devam ediyor"},
            ]
            self._save(job)
            self._launch(job)
            n += 1
        return n

    async def _run(self, job: dict[str, Any]) -> None:
        def say(agent: str, text: str) -> None:
            job["talk"] = [*job["talk"][-60:], {"agent": agent, "text": text[:500]}]
            self._save(job)

        try:
            job["result"] = await self.design(
                job["brief"], say, job.setdefault("ckpt", {}), lambda: self._save(job)
            )
            job["state"] = "done"
            job.pop("ckpt", None)
        except Exception as exc:  # noqa: BLE001 - a failed design is a finding, not a crash
            log.warning("board_team.failed", error=repr(exc)[:200])
            if not job.get("retried"):  # once more from the checkpoint: a busy or restarted model is the usual cause
                job.update(retried=True)
                say("sistem", f"hata ({type(exc).__name__}), kaldığı yerden bir kez daha deneniyor")
                return await self._run(job)
            job.update(state="failed", error=(str(exc) or type(exc).__name__)[:300])
            self._learn.note(
                "electronics",
                "board_failed",
                f"kart tasarımı başarısız ({job['brief'][:60]}): {str(exc)[:120]}",
            )
        self._save(job)

    # ------------------------------------------------------------ agents
    async def _ask(self, prompt: str, schema: dict[str, Any], tokens: int) -> dict[str, Any]:
        return dict(await self._llm.fill(prompt, schema, profile="param_skill", max_tokens=tokens))

    async def _architect(self, brief: str, problem: str = "") -> dict[str, Any]:
        notes = "(yok)"
        if self._notes is not None:
            notes = (
                "\n".join(f"- {n['title']}: {n['rule']}" for n in self._notes.relevant(brief, 5))
                or "(yok)"
            )
        return await self._ask(
            ARCHITECT_PROMPT.format(brief=brief, notes=notes, problem=problem),
            ARCHITECT_SCHEMA,
            6000,
        )

    async def _pick(self, circuit: dict[str, Any], problem: str = "") -> None:
        parts = "\n".join(
            f"- {p['ref']}: {p['kind']} {p['value']} {p['package']} ({len(p['pins'])} pin)"
            for p in circuit["parts"]
        )
        out = await self._ask(
            PICK_PROMPT.format(catalog=catalog_hint(), parts=parts, problem=problem),
            PICK_SCHEMA,
            1800,
        )
        by_ref = {p["ref"]: p for p in circuit["parts"]}
        for line in out.get("lines", []):
            part = by_ref.get(line["ref"])
            if part is not None:
                part["part_number"], part["supplier"] = line["part_number"], line["supplier"]

    async def _find(self, line: dict[str, Any]) -> dict[str, Any]:
        """Look one BOM line up at the Turkish shops; only a quote from the shop's own page counts."""
        if line["kind"] in GENERIC and "_" in line["part_number"]:
            return {
                "status": "genel",
                "note": "standart pasif parça: Türkiye'deki elektronik mağazalarında bulunur (fiyat doğrulanmadı)",
                "shop": "",
                "url": SHOPS["Direnc.net"].format(
                    q=quote_plus(f"{KIND_TR[line['kind']]} {line['value']} {line['package']}")
                ),
            }
        query = line["part_number"]
        tried = []
        for shop, template in SHOPS.items():
            url = template.format(q=quote_plus(query))
            tried.append(url)
            try:
                page = await self._mcp.call("fetch", "fetch", {"url": url}, 40)
                text = str(page.get("text", ""))[:6000] if isinstance(page, dict) else ""
                if not text:
                    continue
                from neml_brain.llm.untrusted import wrap

                found = await self._ask(
                    FIND_PROMPT.format(query=query) + "\n\n" + wrap(text, "web", 6000),
                    FIND_SCHEMA,
                    300,
                )
            except Exception as exc:  # noqa: BLE001 - a shop that is down or blocks us is just not an answer
                log.info("board_team.shop_failed", shop=shop, error=str(exc)[:100])
                continue
            quote = squash(str(found.get("quote", "")))
            if found.get("found") and len(quote) > 12 and quote in squash(text):
                price = float(found.get("price_try") or 0)
                grounded_price = (
                    price
                    if price
                    and re.sub(r"\D", "", f"{price:g}".split(".")[0]) in re.sub(r"\D", "", quote)
                    else 0.0
                )
                return {
                    "status": "bulundu" if found.get("stock") != "yok" else "stokta yok",
                    "shop": shop,
                    "price_try": grounded_price,
                    "stock": found.get("stock"),
                    "url": str(found.get("url") or url)[:200],
                    "quote": found["quote"],
                }
        return {
            "status": "doğrulanamadı",
            "shop": "",
            "url": tried[0],
            "note": "mağaza sayfalarında ürün bulunamadı ya da sayfa okunamadı; arama bağlantısı verildi",
        }

    # ------------------------------------------------------------ the flow
    async def _source(
        self, circuit: dict[str, Any], sourcing: dict[str, dict[str, Any]], say: Any
    ) -> None:
        """Turkish sourcing of every BOM line; what cannot be bought goes back to the picker for a substitute (once)."""
        for round_no in range(2):
            lines = bom_lines(circuit["parts"])
            say(
                "tedarik",
                f"Türkiye temini kontrol ediliyor ({len(lines)} kalem, tur {round_no + 1})",
            )
            for line in lines:
                if (
                    line["part_number"] not in sourcing
                    or sourcing[line["part_number"]]["status"] == "stokta yok"
                ):
                    sourcing[line["part_number"]] = await self._find(line)
            missing = [
                line for line in lines if sourcing[line["part_number"]]["status"] == "stokta yok"
            ]
            if not missing or round_no == 1:
                return
            say(
                "tedarik", "Türkiye'de bulunamayan: " + ", ".join(m["part_number"] for m in missing)
            )
            await self._pick(
                circuit,
                "\n\nŞu parçalar Türkiye mağazalarında stokta yok, eşdeğer ve bulunabilir bir alternatif seç: "
                + ", ".join(f"{m['part_number']} ({' '.join(m['refs'])})" for m in missing),
            )
            say("malzeme", "alternatifler seçildi")

    async def _erc(self, built: dict[str, Any]) -> tuple[bool, str]:
        try:
            await self._mcp.call("kicad", "run_erc", {"schematic_path": built["schematic"]}, 180)
            return True, ""
        except Exception as exc:  # noqa: BLE001 - the violations are the data the architect needs
            return False, str(exc)[:600]

    async def design(
        self,
        brief: str,
        say: Any = lambda _a, _t: None,
        ckpt: dict[str, Any] | None = None,
        save: Any = lambda: None,
    ) -> dict[str, Any]:
        """`ckpt` holds what is already decided (circuit, picked parts, sourcing, ERC round): a restarted job reuses it."""
        ckpt = {} if ckpt is None else ckpt
        if "circuit" not in ckpt:
            spec = await self._race(brief, say)
            say("mimar", f"{spec['purpose']} ({len(spec['circuit']['parts'])} parça)")
            ckpt.update(
                circuit=spec["circuit"],
                name=spec["board_name"],
                purpose=spec["purpose"],
                sourcing={},
                erc_round=0,
                picked=False,
            )
            save()
        circuit, name, purpose = ckpt["circuit"], ckpt["name"], ckpt["purpose"]
        sourcing: dict[str, dict[str, Any]] = ckpt["sourcing"]
        built: dict[str, Any] = {}
        for erc_round in range(ckpt["erc_round"], 3):
            if not ckpt["picked"]:
                say("malzeme", "malzeme listesini seçiyorum")
                await self._pick(circuit)
                ckpt.update(circuit=circuit, picked=True)
                save()
            await self._source(circuit, sourcing, say)
            ckpt.update(circuit=circuit)
            save()
            built = await self._route_until_clean(circuit, name, await self._build(circuit, name), say)
            ok, detail = await self._erc(built)
            if ok or erc_round == 2:
                break
            say("eleştirmen", f"ERC (elektrik kuralı) hataları var: {detail[:200]}")
            say("mimar", "devreyi ERC hatalarına göre düzeltiyorum")
            current = json.dumps(circuit, ensure_ascii=False, separators=(",", ":"))[:5000]
            fixed = await self._architect(
                brief,
                f"\n\nMevcut devre: {current}\nKiCad ERC hataları: {detail}. Pin elektriksel türlerini (aynı nette iki output ya da iki power_out olmasın; "
                "güç girişi power_in, kaynağı power_out olsun) ve bağlantıları düzelt, düzeltilmiş devrenin tamamını yaz.",
            )
            circuit, name = fixed["circuit"], fixed["board_name"]
            try:
                await self._build(circuit, name)
            except Exception as exc:  # noqa: BLE001 - keep the previous circuit when the fix is not even valid
                say("yönlendirme", f"düzeltme çizilemedi: {str(exc)[:140]}")
                break
            ckpt.update(circuit=circuit, name=name, picked=False, erc_round=erc_round + 1)
            save()
        if not built:  # restarted after the last round: draw the board again from the checkpoint
            built = await self._route_until_clean(circuit, name, await self._build(circuit, name), say)
        files = await self._finish(circuit, name, built, sourcing, say)
        review = await self._ask(REVIEW_PROMPT.format(summary=self._summary(circuit, files)), REVIEW_SCHEMA, 700)
        say("eleştirmen", f"{review['verdict']}: " + "; ".join(review["risks"][:3]))
        found = sum(1 for s in sourcing.values() if s["status"] in ("bulundu", "genel"))
        return {**files, "purpose": purpose, "board_name": name, "review": review, "sourcing_ok": f"{found}/{len(sourcing)}"}

    async def _race(self, brief: str, say: Any) -> dict[str, Any]:
        """The architect draws `variants` circuits (different approaches); KiCad's electrical rules count the errors of each,
        the one with the fewest wins and the race stops early at a clean one. With one variant it is just the first buildable circuit."""
        best: tuple[float, dict[str, Any]] | None = None
        last = ""
        for i in range(self.variants):
            hint = VARIANT_HINTS[i % len(VARIANT_HINTS)]
            problem, spec, built = hint, None, None
            for attempt in range(MAX_ATTEMPTS):
                say("mimar", f"devreyi tasarlıyorum (varyant {i + 1}, deneme {attempt + 1})")
                try:
                    spec = await self._architect(brief, problem)
                    built = await self._build(spec["circuit"], spec["board_name"])
                    break
                except Exception as exc:  # noqa: BLE001 - the server's message (or a cut-off answer) is what the architect needs
                    spec, last = None, str(exc)[:200]
                    problem = hint + f"\n\nÖnceki taslak reddedildi: {str(exc)[:300]}. Düzelt."
                    say("yönlendirme", f"kart çizilemedi: {str(exc)[:160]}")
            if spec is None or built is None:
                continue
            if self.variants == 1:
                return spec
            ok, detail = await self._erc(built)
            found = re.search(r"(\d+) ERC error", detail)
            errors = 0 if ok else int(found.group(1)) if found else 99
            say("eleştirmen", f"varyant {i + 1}: {errors} elektrik kuralı hatası, {len(spec['circuit']['parts'])} parça")
            score = -errors - 0.05 * len(spec["circuit"]["parts"])
            if best is None or score > best[0]:
                best = (score, spec)
            if errors == 0:
                break
        if best is None:
            raise RuntimeError("devre geçerli çıkmadı: " + last)
        return best[1]

    async def _build(self, circuit: dict[str, Any], name: str) -> dict[str, Any]:
        out = self._work / uuid.uuid4().hex[:8]
        return dict(
            await self._mcp.call(
                "kicad",
                "build_circuit",
                {"circuit": circuit, "out_dir": str(out), "name": name},
                120,
            )
        ) | {"out": str(out)}

    async def _drc(self, built: dict[str, Any]) -> tuple[list[str], int]:
        """KiCad's verdict on the board: (problems in plain words, unconnected items)."""
        problems: list[str] = []
        unconnected = 0
        try:
            out = await self._mcp.call("kicad", "run_drc", {"board_path": built["board"]}, 180)
            unconnected = int(out.get("unconnected", 0))
        except Exception as exc:  # noqa: BLE001 - a rule violation is the data the router works with
            problems.append(f"DRC: {str(exc)[:200]}")
        return problems, unconnected

    async def _route_until_clean(
        self, circuit: dict[str, Any], name: str, built: dict[str, Any], say: Any
    ) -> dict[str, Any]:
        for round_no in range(1, MAX_ROUNDS + 1):
            problems, unconnected = await self._drc(built)
            unrouted = list(built["routing"]["unrouted"])
            if unrouted:
                problems.append("çizilemeyen net'ler: " + ", ".join(unrouted))
            if unconnected:
                problems.append(
                    f"KiCad {unconnected} bağlantısız öğe gördü (iz bir pedin bakırına değmiyor olabilir)"
                )
            built.setdefault("rounds", []).append({"round": round_no, "routed": len(built["routing"]["routed"]), "unrouted": unrouted, "problems": [q[:240] for q in problems]})
            say(
                "yönlendirme",
                f"tur {round_no}: {len(built['routing']['routed'])} net çizildi, çizilemeyen {len(unrouted)}, KiCad bağlantısız {unconnected}"
                + (f", {problems[0]}" if problems and not unrouted else ""),
            )
            if not problems:
                built["clean"] = True
                return built
            if round_no == MAX_ROUNDS:
                break
            w, h = built["size_mm"]
            places = ", ".join(
                f"{ref}=({x:.0f},{y:.0f})" for ref, (x, y) in built["places"].items()
            )
            fix = await self._ask(
                FIX_PROMPT.format(
                    w=w,
                    h=h,
                    track=circuit.get("track_mm", 0.25),
                    problems="; ".join(problems),
                    places=places,
                ),
                FIX_SCHEMA,
                700,
            )
            say("yönlendirme", fix["diagnosis"])
            circuit["placement"] = {
                **built["places"],
                **{m["ref"]: [m["x"], m["y"]] for m in fix["moves"] if m["ref"] in built["places"]},
            }
            circuit["track_mm"], circuit["size"] = (
                fix["track_mm"],
                [fix["width_mm"], fix["height_mm"]],
            )
            rounds = built["rounds"]
            try:
                built = await self._build(circuit, name)
            except Exception as exc:  # noqa: BLE001 - a bad move (off the board): say so and keep the last good build
                say("yönlendirme", f"hamle reddedildi: {str(exc)[:140]}")
                circuit.pop("placement", None)
                circuit.pop("size", None)
                built = await self._build(circuit, name)
            built["rounds"] = rounds
        built["clean"] = False
        self._learn.note(
            "electronics",
            "routing_unclean",
            f"{name}: {MAX_ROUNDS} turda temiz yönlendirme çıkmadı ({', '.join(built['routing']['unrouted']) or 'DRC'})",
        )
        return built

    async def _finish(
        self,
        circuit: dict[str, Any],
        name: str,
        built: dict[str, Any],
        sourcing: dict[str, dict[str, Any]],
        say: Any,
    ) -> dict[str, Any]:
        out = Path(built["out"])
        pictures = await self._mcp.call(
            "kicad",
            "render",
            {
                "schematic_path": built["schematic"],
                "board_path": built["board"],
                "out_dir": str(out / "svg"),
            },
            180,
        )
        erc: dict[str, Any]
        try:
            res = await self._mcp.call(
                "kicad", "run_erc", {"schematic_path": built["schematic"]}, 180
            )
            erc = {"passed": True, "warnings": res.get("warnings", 0)}
        except Exception as exc:  # noqa: BLE001
            erc = {"passed": False, "detail": str(exc)[:200]}
        second: dict[str, Any]
        try:  # a second reader of the board file; it should agree with KiCad
            second = await self._mcp.call("kicad", "cross_check", {"circuit": circuit, "board_path": built["board"]}, 60)
        except Exception as exc:  # noqa: BLE001 - the extra check never fails a board
            second = {"passed": None, "issues": [f"çapraz kontrol çalışmadı: {str(exc)[:80]}"]}
        if second["passed"] is False and built.get("clean"):
            say("eleştirmen", "ikinci okuyucu KiCad'den farklı düşünüyor: " + "; ".join(second["issues"][:2]))
            self._learn.note("electronics", "crosscheck", f"{name}: KiCad temiz dedi, ikinci okuyucu: {second['issues'][0][:100]}", once=True)
        urls: dict[str, str] = {}
        if self._uploader is not None:
            for key, path in {
                "schematic_svg": Path(pictures["schematic_svg"]),
                "board_svg": Path(pictures["board_svg"]),
                "schematic": Path(built["schematic"]),
                "board": Path(built["board"]),
                "bom": Path(built["bom"]),
            }.items():
                url = await self._uploader.upload(path, path.suffix.lstrip("."))
                if url:
                    urls[key] = url
        rows: list[dict[str, Any]] = [
            dict(r)
            for r in csv.DictReader(io.StringIO(Path(built["bom"]).read_text(encoding="utf-8")))
        ]
        for row in rows:
            row["tr"] = sourcing.get(row.get("part_number", ""), {})
        total = sum(float(r["tr"].get("price_try") or 0) * int(r.get("qty") or 1) for r in rows)
        say("tedarik", f"Türkiye'de fiyatı doğrulanan kalemlerin toplamı ≈ {total:.0f} TL")
        return {
            "urls": urls,
            "bom": rows,
            "erc": erc,
            "crosscheck": second,
            "routing": built["routing"],
            "clean": bool(built.get("clean")),
            "rounds": built.get("rounds", []),
            "size_mm": built["size_mm"],
            "tr_total_try": round(total, 2),
            "circuit": circuit,
        }

    @staticmethod
    def _summary(circuit: dict[str, Any], files: dict[str, Any]) -> str:
        kinds = Counter(p["kind"] for p in circuit["parts"])
        nets = sorted({pin[3] for p in circuit["parts"] for pin in p["pins"]})
        return f"{circuit['title']}: {dict(kinds)}, net'ler {nets[:20]}, yönlendirme temiz={files['clean']}, ERC={files['erc']}"
