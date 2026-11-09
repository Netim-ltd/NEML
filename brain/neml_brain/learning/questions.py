# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The lab's questions to its owner, and the designs worth copying.

A running design never waits for an answer (the CPU is too slow to sit idle): it asks, carries on with its best guess, and the answer
is shown to every later plan as a rule of the owner. `good_plans` keeps plans that passed every gate, so the next plan of a similar
request starts from a design that is known to work instead of a blank page.
# ponytail: word overlap for 'similar', a file per kind; an embedding index when there are hundreds of them."""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

MAX_OPEN = 5  # a lab that asks everything is noise; past this the oldest open question is dropped


def _read(path: Path) -> list[dict[str, Any]]:
    try:
        return list(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return []


def _write(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


class Questions:
    def __init__(self, root: Path) -> None:
        self._q, self._g = root / "questions.json", root / "good_plans.json"

    def ask(self, text: str, why: str = "") -> bool:
        """Open a question unless the same one is already open or was answered."""
        rows = _read(self._q)
        if any(r["text"] == text for r in rows):
            return False
        rows.append({"id": uuid.uuid4().hex[:8], "text": text[:300], "why": why[:300], "at": time.time(), "answer": None})
        open_ = [r for r in rows if r["answer"] is None]
        if len(open_) > MAX_OPEN:
            rows.remove(open_[0])
        _write(self._q, rows[-60:])
        return True

    def answer(self, qid: str, text: str) -> bool:
        rows = _read(self._q)
        for r in rows:
            if r["id"] == qid and text.strip():
                r.update(answer=text.strip()[:400], answered_at=time.time())
                _write(self._q, rows)
                return True
        return False

    def all(self) -> list[dict[str, Any]]:
        return _read(self._q)[-20:]

    def rules(self) -> str:
        """The owner's answers, as a block for the planning prompt."""
        got = [r for r in _read(self._q) if r["answer"]][-8:]
        return ("\nSahibinin cevapları (bağlayıcı):\n" + "\n".join(f"- {r['text']} -> {r['answer']}" for r in got)) if got else ""

    # ---- designs worth copying
    def keep(self, brief: str, plan: dict[str, Any]) -> None:
        rows = [r for r in _read(self._g) if r["name"] != plan["name"]]
        rows.append({"name": plan["name"], "brief": brief[:200], "plan": plan, "at": time.time()})
        _write(self._g, rows[-30:])

    def example(self, brief: str) -> str:
        """The kept plan whose request shares the most words with this one, as a compact listing (empty when none)."""
        words = set(re.findall(r"\w{4,}", brief.lower()))
        best = max(_read(self._g), key=lambda r: len(words & set(re.findall(r"\w{4,}", r["brief"].lower()))), default=None)
        if best is None or not words & set(re.findall(r"\w{4,}", best["brief"].lower())):
            return ""
        lines = []
        for lk in best["plan"]["links"]:
            j = lk["joint"]
            lines.append(
                f"{lk['name']} (parent {lk['parent'] or '-'}, {lk['source']}{' ' + lk['part'] if lk.get('part') else ''}, "
                f"boyut {'x'.join(f'{v:g}' for v in lk['dims_mm'])}, kütle {lk['mass_g']:g} g, eklem {j['type']} {j['x']:g},{j['y']:g},{j['z']:g} eksen {j['axis']})"
            )
        return f"\nTüm kapılardan geçmiş benzer bir tasarım ('{best['brief'][:80]}'); yapısından yararlan, kopyalama:\n" + "\n".join(lines)
