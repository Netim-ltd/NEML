# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""After every model the lab makes, its agents sit down together.

Six specialists (mechanical, electronics, structure, simulation, manufacturing, critic) each read the
design and say what is wrong and what is missing; in a second round each answers the others; a
moderator turns the discussion into: what is missing, how the robot should work, concrete actions and
topics worth researching. Then the loop closes:

* every action is written as a lesson of the `design` area (accepted when at least three specialists
  independently named the same kind of fix);
* every research topic is read on the web through the fetch server and kept as RAG notes;
* the next design the lab starts is briefed with what the last review found missing.

Nothing here edits a design: it produces reviews, lessons, notes and the next brief.
"""

from __future__ import annotations

import json
import time
import uuid
from collections import Counter
from typing import Any

import sqlalchemy as sa
import structlog

from .domains import DOMAINS
from .store import LearningStore, fingerprint

log = structlog.get_logger(__name__)

ROLES = {
    "mekanik": "Mekanik mühendis: yapı, mafsallar, aktüatör seçimi, hareket aralığı, parçaların yerleşimi",
    "elektronik": "Elektronik mühendisi: güç, kartlar, sensörler, kablolama, haberleşme",
    "yapisal": "Yapısal analizci: gerilme, sehim, bağlantı ve vida noktaları, malzeme",
    "simulasyon": "Simülasyon test mühendisi: Gazebo dünyaları, denge, devrilme, hangi ortamlarda denenmeli",
    "uretim": "Üretim ve montaj mühendisi: 3B baskı, destek, montaj sırası, bağlantı elemanları, maliyet",
    "elestirmen": "Eleştirmen: en sert haliyle eksikleri, riskleri ve yanlış varsayımları söyler",
}
KINDS = [t["name"] for t in DOMAINS["design"]["tools"]]
STATEMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["message", "findings", "missing", "suggest", "argument", "objection"],
    "properties": {
        "message": {"type": "string", "maxLength": 450},
        "findings": {"type": "array", "maxItems": 3, "items": {"type": "string", "maxLength": 160}},
        "missing": {"type": "array", "maxItems": 3, "items": {"type": "string", "maxLength": 160}},
        "suggest": {"enum": KINDS},
        "argument": {"type": "string", "maxLength": 80},
        "objection": {"type": "string", "maxLength": 160},
    },
}
MODERATOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "verdict",
        "summary",
        "how_it_should_work",
        "missing",
        "actions",
        "research_topics",
    ],
    "properties": {
        "verdict": {"enum": ["hazır", "eksikleri var", "yeniden tasarlanmalı"]},
        "summary": {"type": "string", "maxLength": 300},
        "how_it_should_work": {"type": "string", "maxLength": 500},
        "missing": {"type": "array", "maxItems": 6, "items": {"type": "string", "maxLength": 160}},
        "actions": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "required": ["kind", "argument", "reason"],
                "properties": {
                    "kind": {"enum": KINDS},
                    "argument": {"type": "string", "maxLength": 80},
                    "reason": {"type": "string", "maxLength": 160},
                },
            },
        },
        "research_topics": {
            "type": "array",
            "maxItems": 3,
            "items": {"type": "string", "maxLength": 100},
        },
    },
}
FIRST = (
    "Rolün: {role}.\nAşağıdaki robot tasarımını kendi uzmanlığından incele.\n{design}\n"
    "Kabul edilmiş eski dersler:\n{lessons}\n"
    "Önce toplantıda arkadaşlarına konuşur gibi 2-4 cümlelik doğal bir mesaj yaz (message): ne gördün, neden endişelisin, ne öneriyorsun. "
    "Sonra bulguların (en çok 3), eksiklerin (en çok 3), tek bir önerilen düzeltme türü (suggest + argument) ve varsa itirazın (objection, yoksa boş) yaz."
)
SECOND = (
    "Rolün: {role}.\nİlk turda ekip arkadaşların şunları söyledi:\n{others}\n"
    "Tasarım: {design}\nOnlara cevap ver: katıldığın ya da itiraz ettiğin noktaları objection'a yaz, kendi bulgu/eksik/önerini gerekirse güncelle."
)
MODERATE = (
    "Sen bu robot tasarım toplantısının moderatörüsün. Tasarım:\n{design}\n"
    "Uzmanların iki tur tartışması:\n{talk}\n"
    "Sonuç: genel hüküm (verdict), kısa özet, robotun nasıl çalışması gerektiği (how_it_should_work), eksikler (missing, en çok 6), "
    "uygulanacak adımlar (actions) ve internette araştırılması gereken konular (research_topics, en çok 3) yaz."
)


def tool_args(kind: str, argument: str) -> dict[str, Any]:
    """The moderator's single `argument` as the arguments of the tool it names (its first parameter); a tool without one takes none."""
    for tool in DOMAINS["design"]["tools"]:
        if tool["name"] == kind:
            props = list(tool["parameters"].get("properties", {}))
            return {props[0]: argument} if props and argument else {}
    return {}


def summarize(body: dict[str, Any]) -> str:
    """The design as the specialists read it: links with roles, joints, masses, materials, plus what the analysts found."""
    mech = body.get("mechanical", {})
    lines = [f"Ad: {body.get('genome_id', '?')}  kütle: {mech.get('body_mass_kg', '?')} kg"]
    gen = mech.get("generated")
    if gen:
        lines.append(f"Amaç: {gen.get('purpose', '')}  (istek: {gen.get('brief', '')[:200]})")
        found = gen.get("findings") or []
        lines.append(
            "Sert hakem bulguları (sayıyla ölçüldü, tartışılmaz; yalnızca nasıl düzeltileceğini somut sayılarla öner): " + "; ".join(found)
            if found
            else "Sert hakem bulguları: yok (tork, katalog, devrilme ve çarpışma denetimleri geçti)"
        )
    for e in mech.get("imports", []):
        if e.get("kind") == "stl" and e.get("design"):
            d = e["design"]
            lines.append(
                f"- parça {e['name']}: {d.get('role', '')}, {d.get('material')}, {e.get('size')} mm, hacim {d.get('volume_mm3', 0):.0f} mm3"
            )
        elif e.get("kind") == "urdf":
            for j in (e.get("rig") or {}).get("joints", [])[:24]:
                lines.append(f"- eklem {j['name']}: {j['type']} {j['parent']} -> {j['child']}")
            for name, info in ((e.get("rig") or {}).get("links") or {}).items():
                lines.append(f"- link {name} kütle {info.get('mass', 0) * 1000:.0f} g")
    elec = body.get("electronics")
    if elec and not gen:
        lines.append(f"Elektronik: {json.dumps(elec, ensure_ascii=False)[:400]}")
    return "\n".join(lines)[:3500]


def closing(v: dict[str, Any]) -> str:
    """The moderator's last message in the group: verdict, how it should work, what is missing, what to do."""
    parts = [f"{v['verdict'].capitalize()}. {v['summary']}", f"Nasıl çalışmalı: {v['how_it_should_work']}"]
    if v["missing"]:
        parts.append(chr(10).join(["Eksikler:", *(f"• {x}" for x in v["missing"])]))
    if v["actions"]:
        parts.append(chr(10).join(["Yapılacaklar:", *(f"• {a['kind']}: {a['reason']}" for a in v["actions"])]))
    return (chr(10) * 2).join(parts)


class RoundTable:
    def __init__(self, llm: Any, store: LearningStore, researcher: Any, sessions: Any) -> None:
        self._llm, self._store, self._researcher, self._sessions = llm, store, researcher, sessions
        self._path = store.root / "reviews.json"
        self._dedupe()

    def _dedupe(self) -> None:
        """Older round-table lessons were saved once per vote: keep the first of each identical advice."""
        lessons, seen = self._store.lessons(), set()
        kept = {}
        for key, x in lessons.items():
            same = (x.get("kind"), x.get("situation"), json.dumps(x.get("call"), sort_keys=True))
            if x.get("kind") == "roundtable" and same in seen:
                continue
            seen.add(same)
            kept[key] = x
        if len(kept) != len(lessons):
            self._store.save_lessons(kept)

    def reviews(self) -> dict[str, Any]:
        return dict(self._store._read(self._path))  # noqa: SLF001

    async def _body(self, model: str) -> dict[str, Any] | None:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    sa.text(
                        "SELECT body FROM genomes WHERE name = :n AND status IN ('active','draft','testing') ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"n": model},
                )
            ).first()
        return dict(row[0]) if row else None

    async def review(self, model: str) -> dict[str, Any] | None:
        body = await self._body(model)
        if body is None:
            return None
        design = summarize(body)
        from .propose import hints, shown

        used = [x["id"] for x in shown(self._store, "design")]  # these lessons were in the room: their effect is measured below
        lessons = hints(self._store, "design") or "(yok)"
        first: dict[str, dict[str, Any]] = {}
        for role, text in ROLES.items():
            first[role] = await self._say(FIRST.format(role=text, design=design, lessons=lessons))
        second: dict[str, dict[str, Any]] = {}
        for role, text in ROLES.items():
            others = "\n".join(
                f"- {r}: eksik={s['missing']} öneri={s['suggest']}({s['argument']}) itiraz={s['objection']}"
                for r, s in first.items()
                if r != role
            )
            second[role] = await self._say(SECOND.format(role=text, others=others, design=design))
        talk = "\n".join(
            f"[{r}] tur1: {first[r]['message']} (öneri={first[r]['suggest']}); tur2: {second[r]['message']}"
            for r in ROLES
        )
        chat = [
            {"round": n, "role": role, "text": s["message"]}
            for n, spoken in ((1, first), (2, second))
            for role, s in spoken.items()
            if s.get("message")
        ]
        verdict = await self._llm.fill(
            MODERATE.format(design=design, talk=talk),
            MODERATOR_SCHEMA,
            profile="param_skill",
            max_tokens=1100,
        )
        chat.append({"round": 3, "role": "moderator", "text": closing(verdict)})
        votes = Counter(s["suggest"] for s in [*second.values()] if s["suggest"] != "ask_owner")
        result = {
            "model": model,
            "at": time.time(),
            **verdict,
            "transcript": {"tur1": first, "tur2": second},
            "chat": chat,
            "votes": dict(votes),
        }
        self._measure(used, len(verdict["missing"]))
        learned = await self._close_the_loop(model, result, votes, len(verdict["missing"]))
        result["learned"] = learned
        reviews = self.reviews()
        reviews[model] = result
        self._store._write(self._path, reviews)  # noqa: SLF001
        log.info(
            "roundtable.done",
            model=model,
            verdict=verdict["verdict"],
            lessons=learned["lessons"],
            notes=learned["notes"],
        )
        return result

    def _measure(self, used: list[str], missing: int) -> None:
        """A lesson shown in this review is judged by what the specialists still found missing: after three
        reviews it is `proven` when the mean is below the count at its birth, and is dropped when it is not.
        # ponytail: a noisy yardstick (the designs differ per review); upgrade to paired before/after runs of one design."""
        lessons = self._store.lessons()
        for key in used:
            x = lessons.get(key)
            if not x or "baseline_missing" not in x:
                continue
            x["after"] = [*x.get("after", []), missing][-6:]
            if len(x["after"]) >= 3:
                helped = sum(x["after"]) / len(x["after"]) < x["baseline_missing"]
                x["proven"] = helped
                if not helped:
                    x.update(status="rejected", reason="üç incelemede eksik sayısını azaltmadı", decided_at=time.time())
        self._store.save_lessons(lessons)

    async def _say(self, prompt: str) -> dict[str, Any]:
        return dict(
            await self._llm.fill(prompt, STATEMENT_SCHEMA, profile="param_skill", max_tokens=900)
        )

    async def _close_the_loop(
        self, model: str, result: dict[str, Any], votes: Counter[str], missing: int = 0
    ) -> dict[str, int]:
        """Actions become lessons , research topics become RAG notes."""
        lessons = self._store.lessons()
        made = 0
        for action in result["actions"]:
            if action["kind"] == "research":
                continue
            args = tool_args(action["kind"], action["argument"])
            fp = fingerprint("design", "roundtable", f"{action['kind']}|{args}|{action['reason']}")
            if any(x["fp"] == fp for x in lessons.values()):
                continue  # the same advice again is not a new lesson
            lessons[uuid.uuid4().hex[:12]] = {
                "id": "",
                "fp": fp,
                "baseline_missing": missing,  # how many things the specialists found missing when this was advised
                "domain": "design",
                "kind": "roundtable",
                "situation": f"{model}: {action['reason']}",
                "cause": result["summary"][:300],
                "call": {"name": action["kind"], "arguments": args},
                "source": "roundtable",
                "confidence": None,
                "status": "accepted" if votes.get(action["kind"], 0) >= 3 else "proposed",
                "auto": votes.get(action["kind"], 0) >= 3,
                "ts": time.time(),
                "decided_at": time.time(),
            }
            made += 1
        for key, lesson in lessons.items():
            lesson["id"] = lesson["id"] or key
        self._store.save_lessons(lessons)
        notes = 0
        for topic in result["research_topics"]:
            try:
                got = await self._researcher.learn(topic)
                notes += len(got.get("notes", []))
            except Exception as exc:  # noqa: BLE001 - research is best effort
                log.info("roundtable.research_failed", topic=topic[:60], error=str(exc)[:100])
        return {"lessons": made, "notes": notes}


def next_brief(reviews: dict[str, Any], model: str) -> str | None:
    """A redesign brief from the last review: the original request plus everything the specialists found missing."""
    r = reviews.get(model)
    if not r or r.get("verdict") == "hazır" or not r.get("missing"):
        return None
    return f"{model} robotunun yeni, daha iyi sürümü. Eksikler: {'; '.join(r['missing'][:6])}. Nasıl çalışmalı: {r.get('how_it_should_work', '')[:300]}"
