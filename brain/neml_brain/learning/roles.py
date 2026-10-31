# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every area has its own analyst, critic and engineer.

* analyst  - deterministic checks of the real design (structure, fit/collision, worlds): findings.
* critic   - the language model reads the findings and the design summary and writes a short review
             (what is risky, what to verify first); stored for the panel, never applied.
* engineer - proposes the remedy (the main model) through the
             learning loop; once the owner (or the lab's own consistency vote) accepts it, a *safe*
             remedy is carried out by `apply_lesson`: creating a new simulation world is the only
             one, since it is a validated file nobody depends on. Design changes stay drafts.
"""

from __future__ import annotations

import time
from typing import Any

from neml_brain.evolution import structure
from neml_brain.evolution.worlds import WorldStore

from .store import LearningStore

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"enum": ["ok", "riskli", "kritik"]},
        "risks": {"type": "array", "maxItems": 4, "items": {"type": "string", "maxLength": 200}},
        "verify_first": {"type": "string", "maxLength": 200},
    },
    "required": ["verdict", "risks", "verify_first"],
}
REVIEW_PROMPT = (
    "Bir dört ayaklı robotun {area} analizi şu bulguları verdi:\n{findings}\n"
    "Bir eleştirmen mühendis gibi: genel hüküm (ok/riskli/kritik), en fazla 4 risk ve önce neyin doğrulanacağını yaz."
)


async def audit(
    store: LearningStore,
    llm: Any,
    body: dict[str, Any],
    model: str,
    scene_fit: list[str] | None = None,
) -> dict[str, Any]:
    """Run the analysts on one design, note what they find (once per finding) and keep a critic's review."""
    results: dict[str, Any] = {}
    findings = structure.analyze(body)
    for f in findings:
        store.note(
            "structure",
            "analysis",
            f["text"],
            {"model": model, "severity": f["severity"]},
            once=True,
        )
    results["structure"] = findings
    for text in scene_fit or []:
        store.note("assembly", "fit", f"{model}: {text}", {"model": model}, once=True)
    results["fit"] = scene_fit or []
    for area in ("structure", "fit"):
        items = [f["text"] if isinstance(f, dict) else f for f in results[area]]
        if not items:
            results[f"review_{area}"] = {"verdict": "ok", "risks": [], "verify_first": ""}
            continue
        try:
            review = await llm.fill(
                REVIEW_PROMPT.format(area=area, findings="\n".join(f"- {i}" for i in items[:6])),
                REVIEW_SCHEMA,
                profile="param_skill",
            )
        except Exception:  # noqa: BLE001 - a busy model: the findings stand without a review
            review = {
                "verdict": "riskli",
                "risks": items[:2],
                "verify_first": "",
                "unreviewed": True,
            }
        results[f"review_{area}"] = review
    results["at"] = time.time()
    results["model"] = model
    path = store.root / "audit.json"
    audits = store._read(path)  # noqa: SLF001
    audits[model] = results
    store._write(path, audits)  # noqa: SLF001
    return results


def apply_lesson(lesson: dict[str, Any], worlds: WorldStore) -> str | None:
    """Carry out an accepted lesson when it is safe to do so; returns what happened (None = advice only)."""
    call = lesson["call"]
    if call["name"] == "add_world":
        got = worlds.create(
            call["arguments"].get("template", "hobby_garden"),
            int(call["arguments"].get("difficulty", 1)),
        )
        return f"dünya {got['name']}: " + (
            "hazır" if got["ok"] else "reddedildi: " + "; ".join(got["problems"])
        )
    if call["name"] == "make_world_easier":
        name = str(call["arguments"].get("world", ""))
        info = worlds.index().get(name)
        if info and info["difficulty"] > 1:
            got = worlds.create(info["template"], info["difficulty"] - 1)
            return f"daha kolay dünya {got['name']}: " + ("hazır" if got["ok"] else "reddedildi")
    return None


def apply_accepted(store: LearningStore, worlds: WorldStore) -> list[str]:
    """Every accepted lesson that has a safe action and was not carried out yet."""
    lessons = store.lessons()
    done = []
    for lesson in lessons.values():
        if lesson["status"] == "accepted" and "applied" not in lesson:
            lesson["applied"] = apply_lesson(lesson, worlds) or "yalnızca öneri"
            done.append(f"{lesson['id']}: {lesson['applied']}")
    if done:
        store.save_lessons(lessons)
    return done
