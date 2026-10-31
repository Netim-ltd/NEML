# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The data steward: collects, cleans and audits the lessons of every area (the lab's own remedy data).

It uses no model. Three jobs, one cycle:

1. collect - the hard judges' findings (a layout clash, a weak servo, a missing battery, a tipping robot) are labelled with the
   remedy they demand by fixed rules, with their real numbers, and stored as accepted lessons (`source: judge`); findings are read
   from design results too, once per job;
2. clean   - lessons made by the lab itself (not the owner's own decisions) are rejected when the call is not one of the area's
   tools, the text is too short/long/suspicious, it is a copy, or it contradicts a more frequent label of the same situation;
3. audit   - per area: clean rows, share of each remedy, remedies without any row, written to `steward.json` with a short history.

Nothing here edits a design."""

from __future__ import annotations

import hashlib
import re
import time
from collections import Counter
from typing import Any

import structlog

from .domains import DOMAINS
from .propose import valid_call
from .store import LearningStore

log = structlog.get_logger(__name__)

MIN_TEXT, MAX_TEXT = 12, 400
MAX_PER_TEMPLATE = 40  # one kind of finding, however many numbers: this many rows at most
SUSPICIOUS = re.compile(r"ignore (all |the )?previous|system prompt|talimatları yok say|<\s*/?\s*(script|system)|\bBEGIN PRIVATE KEY", re.I)
SAFETY = 2.0

RULES: list[tuple[re.Pattern[str], str, Any]] = []


def _rule(pattern: str, domain: str):
    def deco(fn: Any) -> Any:
        RULES.append((re.compile(pattern), domain, fn))
        return fn

    return deco


@_rule(r"(\w+) ve (\w+) iç içe giriyor", "design")
def _overlap(m: re.Match[str]) -> dict[str, Any]:
    return {"name": "fix_layout", "arguments": {"part": m.group(2)}}


@_rule(r"^(\w+), bağlı olduğu (\w+) parçasına değmiyor", "design")
def _floating(m: re.Match[str]) -> dict[str, Any]:
    return {"name": "fix_layout", "arguments": {"part": m.group(1)}}


@_rule(r"^(\w+): gereken tork ([\d.]+) kg\*cm", "structure")
def _torque(m: re.Match[str]) -> dict[str, Any]:
    return {"name": "use_stronger_servo", "arguments": {"torque_nm": round(float(m.group(2)) * SAFETY * 0.0980665, 2)}}


@_rule(r"hareketli robotta batarya yok", "design")
def _battery(_m: re.Match[str]) -> dict[str, Any]:
    return {"name": "add_missing_part", "arguments": {"part": "batarya"}}


@_rule(r"hareketli robotta kontrolcü kartı yok", "design")
def _board(_m: re.Match[str]) -> dict[str, Any]:
    return {"name": "add_missing_part", "arguments": {"part": "kontrolcü kartı"}}


@_rule(r"acil durdurma", "design")
def _stop(_m: re.Match[str]) -> dict[str, Any]:
    return {"name": "add_safety_feature", "arguments": {"kind": "acil durdurma"}}


@_rule(r"devrilme payı ([\d.]+)", "assembly")
def _tip(m: re.Match[str]) -> dict[str, Any]:
    return {"name": "widen_stance", "arguments": {"delta_mm": 20 + round(max(0.5 - float(m.group(1)), 0) * 60)}}


@_rule(r"(\w+): parça [\d×]+ mm \(\w[\w-]*\): kiriş tahmini emniyet katsayısı ([\d.]+)", "structure")
def _beam(m: re.Match[str]) -> dict[str, Any]:
    return {"name": "thicken_wall", "arguments": {"part": m.group(1), "wall_mm": round(min(max(1.6 * 2 / max(float(m.group(2)), 0.3), 2.0), 6.0), 1)}}


@_rule(r"^(\w+): [\d.]+ mm, \d+ mm sınırını aşıyor", "cad")
def _too_big(m: re.Match[str]) -> dict[str, Any]:
    return {"name": "split_part", "arguments": {"part": m.group(1)}}


@_rule(r"toplam kütle ([\d.,]+) kg: 0,05", "sim")
def _heavy(m: re.Match[str]) -> dict[str, Any] | None:
    return {"name": "lower_body_mass", "arguments": {"mass_kg": 30}} if float(m.group(1).replace(",", ".")) > 30 else None


def label(text: str) -> tuple[str, dict[str, Any]] | None:
    """The area and remedy a judge finding demands, or None when no rule covers it."""
    for pattern, domain, make in RULES:
        m = pattern.search(text)
        call = make(m) if m else None
        if call:
            return domain, call
    return None


def normal(text: str) -> str:
    return " ".join(re.sub(r"\d+(\.\d+)?", "#", text.lower()).split())


def template(text: str) -> str:
    """A finding with names and numbers blanked: the shape that MAX_PER_TEMPLATE counts."""
    return re.sub(r"\b\w*\d\w*\b|\b[a-z]+_[a-z_0-9]+\b", "_", normal(text))[:80]


class Steward:
    def __init__(self, store: LearningStore) -> None:
        self.store = store
        self._path = store.root / "steward.json"

    def report(self) -> dict[str, Any]:
        return self.store._read(self._path)  # noqa: SLF001

    # ------------------------------------------------------------------ collect
    def ingest(self, findings: list[str], kind: str = "judge") -> int:
        """Label findings and keep them as accepted lessons; returns the new rows."""
        lessons = self.store.lessons()
        counts = Counter(template(x["situation"]) for x in lessons.values() if x.get("source") == "judge" and x["status"] == "accepted")
        have = {x["fp"] for x in lessons.values()}
        made = 0
        for text in findings:
            text = " ".join(str(text).split())
            labelled = label(text)
            if labelled is None:
                continue
            domain, call = labelled
            fp = hashlib.sha256(f"{domain}|{kind}|{text}".encode()).hexdigest()[:16]
            shape = template(text)
            if fp in have or counts[shape] >= MAX_PER_TEMPLATE or not valid_call(domain, call):
                continue
            key = "j" + fp[:11]
            lessons[key] = {
                "id": key,
                "fp": fp,
                "domain": domain,
                "kind": kind,
                "situation": text[:MAX_TEXT],
                "cause": "Sert hakem bulgusu; çözüm kuraldan çıkarıldı.",
                "call": call,
                "source": "judge",
                "confidence": 1.0,
                "status": "accepted",
                "auto": True,
                "ts": time.time(),
                "decided_at": time.time(),
            }
            counts[shape] += 1
            have.add(fp)
            made += 1
        if made:
            self.store.save_lessons(lessons)
        return made

    def harvest(self, jobs: list[dict[str, Any]]) -> int:
        """Findings of finished design jobs (once per job)."""
        state = self.report()
        done = set(state.get("harvested", []))
        made = 0
        for job in jobs:
            if job.get("state") != "done" or job["id"] in done:
                continue
            made += self.ingest(list((job.get("result") or {}).get("problems") or []))
            done.add(job["id"])
        state["harvested"] = sorted(done)[-300:]
        self._write(state)
        return made

    # -------------------------------------------------------------------- clean
    def clean(self) -> dict[str, int]:
        """Reject the lab's own lessons that would teach the wrong thing. Owner decisions are never touched (only reported)."""
        lessons = self.store.lessons()
        stats: Counter[str] = Counter()
        from .roundtable import tool_args

        for x in lessons.values():  # round-table lessons once stored `{argument: ...}`: mend them to the tool's own parameter, also those rejected for it
            args = x["call"].get("arguments", {})
            if x.get("source") == "roundtable" and set(args) == {"argument"} and x["status"] in ("accepted", "rejected"):
                fixed = {"name": x["call"]["name"], "arguments": tool_args(x["call"]["name"], str(args["argument"]))}
                if valid_call(x["domain"], fixed):
                    x["call"] = fixed
                    if x["status"] == "rejected" and str(x.get("reason", "")).startswith("veri ajanı: geçersiz"):
                        x.update(status="accepted", reason="")
                    stats["onarılan"] += 1
        seen: dict[tuple[str, str, str], str] = {}
        votes: dict[tuple[str, str], Counter[str]] = {}
        for x in lessons.values():
            if x["status"] == "accepted":
                votes.setdefault((x["domain"], normal(x["situation"])), Counter())[x["call"]["name"]] += 1

        def own(x: dict[str, Any]) -> bool:
            return bool(x.get("auto")) or x.get("source") in ("roundtable", "judge")

        for key, x in sorted(lessons.items(), key=lambda kv: kv[1]["ts"]):
            if x["status"] != "accepted":
                continue
            reason = None
            text = str(x["situation"])
            norm = normal(text)
            if not valid_call(x["domain"], x["call"]):
                reason = "geçersiz çağrı"
            elif not MIN_TEXT <= len(text) <= MAX_TEXT:
                reason = "metin çok kısa/uzun"
            elif SUSPICIOUS.search(text):
                reason = "şüpheli metin"
            else:
                sig = (x["domain"], norm, f"{x['call']['name']}|{sorted(x['call']['arguments'].items())}")
                tally = votes.get((x["domain"], norm), Counter())
                if sig in seen:
                    reason = "kopya"
                elif len(tally) > 1 and tally[x["call"]["name"]] < max(tally.values()):
                    reason = "çelişki: aynı durum için daha sık verilen etiket var"
                else:
                    seen[sig] = key
            if reason:
                if own(x):
                    x.update(status="rejected", reason=f"veri ajanı: {reason}", decided_at=time.time())
                    stats[reason.split(":")[0]] += 1
                else:
                    x["flag"] = reason  # the owner's own decision: shown in the report, not changed
                    stats["işaretli (sahibin kararı)"] += 1
        if any(v for k, v in stats.items() if not k.startswith("işaretli")):  # noqa: SIM102
            self.store.save_lessons(lessons)
        return dict(stats)

    # -------------------------------------------------------------------- audit
    def audit(self) -> dict[str, Any]:
        """Per area: clean rows, the share of each remedy, remedies without any row, and whether any source feeds the area."""
        out: dict[str, Any] = {}
        for domain, spec in DOMAINS.items():
            rows = self.store.accepted(domain)
            tools = [t["name"] for t in spec["tools"] if t["name"] != "ask_owner"]
            used = Counter(x["call"]["name"] for x in rows)
            notes = []
            if not any(d == domain for _, d, _ in RULES) and not any(x.get("source") == "roundtable" for x in rows):
                notes.append("otomatik veri kaynağı yok")
            out[domain] = {
                "clean": len(rows),
                "by_remedy": dict(used),
                "top_share": round(max(used.values(), default=0) / max(len(rows), 1), 2),
                "missing_remedies": [t for t in tools if not used[t]],
                "notes": notes,
            }
        return out

    def cycle(self, jobs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """One pass: collect, clean, audit, and write the decisions."""
        made = self.harvest(jobs or [])
        cleaned = self.clean()
        audit = self.audit()
        state = self.report()
        history = [*state.get("history", [])[-19:], {"at": time.time(), "harvested": made, "cleaned": cleaned}]
        state.update(at=time.time(), domains=audit, history=history)
        self._write(state)
        log.info("steward.cycle", harvested=made, cleaned=sum(cleaned.values()))
        return state

    def _write(self, state: dict[str, Any]) -> None:
        self.store._write(self._path, state)  # noqa: SLF001
