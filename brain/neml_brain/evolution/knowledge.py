# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Design knowledge the model chat learns from the web and uses when it answers.

`learn(topic)`: the language model names up to three documentation pages (allowlisted hosts
only, enforced again by the fetch server), the pages are fetched as inert text, and the model
distils them into short Turkish design notes under a grammar. A note keeps its source URL and is
marked `unverified` until the owner confirms it; it informs answers and edits, it never changes
a limit (SPEC 13.3) and the fetched text is untrusted data (SPEC 5.4).

Notes live in one JSON file in the artifact directory. `relevant(text)` picks the notes that
share words with a question.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from neml_brain.agents.base import untrusted
from neml_brain.llm.untrusted import wrap

log = structlog.get_logger(__name__)

MAX_PAGES = 3
MAX_NOTES_PER_PAGE = 3
PAGE_CHARS = 6000
MAX_NOTES = 300

PICK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["urls"],
    "properties": {
        "urls": {
            "type": "array",
            "maxItems": MAX_PAGES,
            "items": {"type": "string", "pattern": "^https://[a-z0-9.-]+/[^ ]*$", "maxLength": 200},
        }
    },
}
NOTES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["notes"],
    "properties": {
        "notes": {
            "type": "array",
            "maxItems": MAX_NOTES_PER_PAGE,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "rule", "quote"],
                "properties": {
                    "area": {"enum": ["cad", "robot", "electronics", "learning"]},
                    "title": {"type": "string", "maxLength": 50},
                    "rule": {"type": "string", "maxLength": 200},
                    "quote": {"type": "string", "maxLength": 160},
                },
            },
        }
    },
}
PICK_PROMPT = (
    "The operator wants to learn about a robot design topic. Name up to three documentation pages "
    "that would explain it (leg and joint proportions, servo mounting, fit and clearances, 3D "
    "print design rules, quadruped gait and anatomy). Only these hosts are reachable: {hosts}. "
    "Use exact article or document URLs you are confident exist, e.g. "
    "https://en.wikipedia.org/wiki/Quadrupedal_robot. Topic: {topic}"
)
NOTES_PROMPT = (
    "From the page text below write at most {n} short design notes in Turkish that help this lab: area=cad (3D parts from boxes, "
    "cylinders, spheres with cut/fuse; printing rules, wall thickness, fits), robot (mechanics, servos, stability, gaits), "
    "electronics (KiCad boards, power, I2C, layout) or learning (how an agent improves itself: benchmarks, skill libraries, rule "
    "search, evaluation). A concrete rule, ratio, clearance or method. Use only what the page states; if it has nothing relevant "
    "return an empty list. Every note must carry 'quote': one sentence copied word for word from the page that supports it. Topic: {topic}"
)
WORD = re.compile(r"[a-zçğıöşü0-9]{4,}", re.IGNORECASE)


def squash(text: str) -> str:
    return " ".join(text.lower().split())


def words(text: str) -> set[str]:
    return {w.lower()[:6] for w in WORD.findall(text)}  # crude stemming: Turkish suffixes vary


class KnowledgeBase:
    def __init__(self, directory: Path) -> None:
        self._path = directory / "knowledge" / "notes.json"

    def all(self) -> list[dict[str, Any]]:
        try:
            return list(json.loads(self._path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return []

    def _save(self, notes: list[dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(notes[-MAX_NOTES:], ensure_ascii=False), encoding="utf-8")

    def add(self, topic: str, source: str, items: list[dict[str, str]]) -> list[dict[str, Any]]:
        notes = self.all()
        have = {n["rule"] for n in notes}
        fresh = [
            {
                "id": uuid.uuid4().hex[:8],
                "topic": topic,
                "area": i.get("area", "robot"),
                "title": i["title"].strip(),
                "rule": i["rule"].strip(),
                "source": source,
                "quote": i.get("quote", ""),
                "learned_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "status": "unverified",
            }
            for i in items
            if i["rule"].strip() and i["rule"].strip() not in have
        ]
        self._save(notes + fresh)
        return fresh

    def forget(self, note_id: str) -> bool:
        notes = self.all()
        kept = [n for n in notes if n["id"] != note_id]
        if len(kept) != len(notes):
            self._save(kept)
        return len(kept) != len(notes)

    def untested(self, area: str, limit: int = 3) -> list[dict[str, Any]]:
        """Notes of an area that no experiment has judged yet (the fewest tries first)."""
        rows = [n for n in self.all() if n.get("area", "robot") == area and n["status"] == "unverified"]
        return sorted(rows, key=lambda n: n.get("tries", 0))[:limit]

    def judge(self, note_id: str, kept: bool, evidence: dict[str, Any], max_tries: int = 2) -> str | None:
        """Record an experiment on a note: verified when it helped, rejected after `max_tries` failed tries. Returns the new status."""
        notes = self.all()
        for n in notes:
            if n["id"] != note_id:
                continue
            n["tries"] = n.get("tries", 0) + 1
            n["evidence"] = [*n.get("evidence", []), evidence][-4:]
            if kept:
                n["status"] = "verified"
            elif n["tries"] >= max_tries:
                n["status"] = "rejected"
            self._save(notes)
            return str(n["status"])
        return None

    def relevant(self, text: str, limit: int = 5) -> list[dict[str, Any]]:
        wanted = words(text)
        scored = [
            (len(wanted & words(f"{n['topic']} {n['title']} {n['rule']}")) + (2 if n["status"] == "verified" else 0), n)
            for n in self.all()
            if n["status"] != "rejected"  # a note an experiment disproved is not shown to the model again
        ]
        return [n for score, n in sorted(scored, key=lambda t: -t[0])[:limit] if score > 0]


class Researcher:
    def __init__(self, mcp: Any, llm: Any, base: KnowledgeBase) -> None:
        self._mcp, self._llm, self.base = mcp, llm, base

    async def learn(self, topic: str) -> dict[str, Any]:
        hosts = ", ".join((await self._mcp.call("fetch", "allowlist", {})) or [])
        picked = await self._llm.fill(
            untrusted(PICK_PROMPT.format(hosts=hosts, topic="(below)"), topic),
            PICK_SCHEMA,
            profile="param_skill",
        )
        return await self.learn_pages(topic, list(picked.get("urls") or []))

    async def learn_pages(self, topic: str, urls: list[str]) -> dict[str, Any]:
        """Read these exact pages (the fetch server still enforces its allowlist) and keep grounded notes."""  # noqa: E501
        learned: list[dict[str, Any]] = []
        read: list[str] = []
        failed: list[str] = []
        for url in urls[:MAX_PAGES]:
            try:
                page = await self._mcp.call("fetch", "fetch", {"url": url}, 40)
            except Exception as exc:  # noqa: BLE001 - one dead link must not stop the others
                failed.append(f"{url}: {str(exc)[:80]}")
                continue
            text = str(page.get("text", ""))[:PAGE_CHARS] if isinstance(page, dict) else ""
            if not text:
                failed.append(f"{url}: boş sayfa")
                continue
            read.append(url)
            try:
                out = await self._llm.fill(
                    NOTES_PROMPT.format(n=MAX_NOTES_PER_PAGE, topic=topic[:200])
                    + "\n\n"
                    + wrap(text, "web", PAGE_CHARS),
                    NOTES_SCHEMA,
                    profile="param_skill",
                )
            except Exception as exc:  # noqa: BLE001 - a page the model cannot digest is skipped
                failed.append(f"{url}: {str(exc)[:80]}")
                continue
            haystack = squash(text)
            grounded = [
                n
                for n in out.get("notes") or []
                if squash(str(n.get("quote", ""))) in haystack
                and len(squash(str(n.get("quote", "")))) > 20
            ]
            learned += self.base.add(topic[:120], url, grounded)
        log.info("knowledge.learned", topic=topic[:80], pages=len(read), notes=len(learned))
        return {"topic": topic, "pages": read, "failed": failed, "notes": learned}
