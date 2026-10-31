# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the lab has seen go wrong (events), what it proposes (lessons) and the models trained from
the accepted lessons. Plain JSON files on the shared artifact volume: the brain, the autonomy loop
and the trainer all read and write them, and a lost line costs one observation, not the lab."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from .domains import DOMAINS

MAX_EVENTS = 5000


def default_dir() -> Path:
    return Path(os.environ.get("NEML_ARTIFACT_DIR", ".")) / "learning"


def fingerprint(domain: str, kind: str, text: str) -> str:
    digits = "".join("#" if c.isdigit() else c for c in text.lower())
    return hashlib.sha256(f"{domain}|{kind}|{digits}".encode()).hexdigest()[:16]


class LearningStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self._events = self.root / "events.jsonl"
        self._lessons = self.root / "lessons.json"
        self._models = self.root / "models.json"

    # ---- events
    def note(
        self,
        domain: str,
        kind: str,
        text: str,
        context: dict[str, Any] | None = None,
        once: bool = False,
    ) -> bool:
        """Remember one thing that went wrong. False for an unknown area or a repeat within the hour."""
        if domain not in DOMAINS or not text.strip():
            return False
        fp = fingerprint(domain, kind, text)
        now = time.time()
        for e in reversed(self.events()[-(5000 if once else 200) :]):
            if e["fp"] == fp and (once or now - e["ts"] < 3600):
                return False
        row = {
            "fp": fp,
            "ts": now,
            "domain": domain,
            "kind": kind,
            "text": text[:400],
            "context": context or {},
        }
        with self._events.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return True

    def events(self) -> list[dict[str, Any]]:
        if not self._events.exists():
            return []
        out = []
        for line in self._events.read_text(encoding="utf-8").splitlines()[-MAX_EVENTS:]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a torn append
        return out

    # ---- lessons
    def lessons(self) -> dict[str, dict[str, Any]]:
        return self._read(self._lessons)

    def save_lessons(self, lessons: dict[str, dict[str, Any]]) -> None:
        self._write(self._lessons, lessons)

    def unanswered(self) -> list[dict[str, Any]]:
        """Events (newest first, one per fingerprint) that no lesson covers yet."""
        covered = {les["fp"] for les in self.lessons().values()}
        seen: set[str] = set()
        out = []
        for e in reversed(self.events()):
            if e["fp"] not in covered and e["fp"] not in seen:
                seen.add(e["fp"])
                out.append(e)
        return out

    def decide(self, lesson_id: str, decision: str) -> dict[str, Any] | None:
        lessons = self.lessons()
        if lesson_id not in lessons or decision not in ("accepted", "rejected"):
            return None
        lessons[lesson_id]["status"] = decision
        lessons[lesson_id]["decided_at"] = time.time()
        self.save_lessons(lessons)
        return lessons[lesson_id]

    def accepted(self, domain: str) -> list[dict[str, Any]]:
        return [
            x
            for x in self.lessons().values()
            if x["domain"] == domain and x["status"] == "accepted"
        ]

    def state(self) -> dict[str, Any]:
        events, lessons = self.events(), self.lessons()
        return {
            "domains": {
                d: {
                    "label": spec["label"],
                    "events": sum(1 for e in events if e["domain"] == d),
                    "accepted": sum(
                        1
                        for x in lessons.values()
                        if x["domain"] == d and x["status"] == "accepted"
                    ),
                }
                for d, spec in DOMAINS.items()
            },
            "lessons": sorted(
                lessons.values(), key=lambda x: (x["status"] != "proposed", -x["ts"])
            )[:60],
            "waiting_events": len(self.unanswered()),
            "radar": self._read(self.root / "radar.json") | {"notes": self._notes_count()},
            "sweeps": self._read(self.root / "sweeps.json"),
            "audit": self._read(self.root / "audit.json"),
            "worlds": self._read(self.root.parent / "worlds" / "index.json"),
        }

    def _notes_count(self) -> int:
        try:
            return len(
                json.loads(
                    (self.root.parent / "knowledge" / "notes.json").read_text(encoding="utf-8")
                )
            )
        except (OSError, ValueError):
            return 0

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _write(path: Path, data: dict[str, Any]) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)


def note(domain: str, kind: str, text: str, context: dict[str, Any] | None = None) -> None:
    """Fire-and-forget from anywhere in the lab: learning must never break the work it watches."""
    try:
        LearningStore().note(domain, kind, text, context)
    except Exception:  # noqa: BLE001, S110
        pass
