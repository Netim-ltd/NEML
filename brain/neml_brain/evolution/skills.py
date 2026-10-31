# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Recipes that were checked and worked, kept to show the model next time (as in Voyager's skill library).

A recipe is stored only after a check: a benchmark case whose volume and box were right, or a part of a design
that passed the structural gate. Looking one up is a word overlap with the new part's description (no new
dependency). A recipe is plain data and is only ever shown to the model as an example, never run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from neml_brain.evolution.knowledge import words

MAX_SKILLS = 120
SHOWN_CHARS = 700  # a recipe longer than this is not shown (it would crowd the prompt)


class SkillLibrary:
    def __init__(self, root: Path) -> None:
        self._path = root / "skills.json"

    def all(self) -> list[dict[str, Any]]:
        try:
            return list(json.loads(self._path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return []

    def add(self, key: str, text: str, recipe: dict[str, Any], source: str) -> None:
        """Keep a checked recipe under `key` (a new one for the same key replaces the old)."""
        rows = [s for s in self.all() if s["key"] != key]
        rows.append({"key": key, "text": text[:300], "recipe": recipe, "source": source})
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(rows[-MAX_SKILLS:], ensure_ascii=False), encoding="utf-8")

    def similar(self, text: str, exclude: str | None = None, limit: int = 2) -> list[dict[str, Any]]:
        """The stored recipes whose description shares most words with `text`; `exclude` is a key to skip
        (a benchmark case must not be shown its own answer)."""
        wanted = words(text)
        scored = [
            (len(wanted & words(s["text"])), s)
            for s in self.all()
            if s["key"] != exclude and len(json.dumps(s["recipe"])) <= SHOWN_CHARS
        ]
        return [s for n, s in sorted(scored, key=lambda t: -t[0])[:limit] if n > 0]

    def examples(self, text: str, exclude: str | None = None) -> str:
        """The prompt addition for a part: the closest checked recipes, or nothing."""
        rows = self.similar(text, exclude)
        if not rows:
            return ""
        shown = " | ".join(f"{s['text'][:120]} => {json.dumps(s['recipe'], ensure_ascii=False)}" for s in rows)
        return f" Benzer, doğrulanmış tarif örnekleri (kopyalama, uyarla): {shown}"
