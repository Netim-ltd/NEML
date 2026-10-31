# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The lab's own decisions, so nothing waits for the owner: lessons, and the data a later fine-tuning would use.

* decide - every lesson still `proposed` is judged by the lab: it is accepted when the fixed rules of the data steward name the same
  remedy, or when a fresh, differently worded question to the model gives the same remedy at least once in two tries; it is rejected
  when it only asks the owner, is invalid, or the model disagrees both times. The decision and its reason are written on the lesson
  (`auto: true`), so the owner can read them and overrule any of them later.
* export - the accepted lessons and the checked part recipes become a chat-style training file (`lora/sft.jsonl`), rebuilt daily.
  Nothing trains here: the main model is an 80B mixture-of-experts on a CPU, which cannot be fine-tuned in the background; the file
  is what a GPU run (scripts/platform/lora_worker.py) would read.

Physical things (printing, ordering, moving a robot) are not decided here: they stay approvals."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import structlog

from .propose import PROMPT2, schema, valid_call
from .steward import label
from .store import LearningStore

log = structlog.get_logger(__name__)

PER_TICK = 4  # the model is slow: a few lessons per round
VOTES = 2


async def agree(llm: Any, lesson: dict[str, Any]) -> bool:
    """Does a fresh question give the lesson's remedy at least once in VOTES tries?"""
    from .domains import DOMAINS

    domain = lesson["domain"]
    prompt = PROMPT2.format(text=lesson["situation"], domain=DOMAINS[domain]["label"], tools=", ".join(t["name"] for t in DOMAINS[domain]["tools"]))
    for _ in range(VOTES):
        try:
            out = await llm.fill(prompt, schema(domain), profile="param_skill")
        except Exception as exc:  # noqa: BLE001 - a busy model leaves the lesson for the next round
            raise RuntimeError(str(exc)[:100]) from exc
        call = out.get("call")
        if valid_call(domain, call) and call["name"] == lesson["call"]["name"]:
            return True
    return False


async def decide(store: LearningStore, llm: Any) -> dict[str, int]:
    """Judge up to PER_TICK proposed lessons; returns the counts."""
    lessons = store.lessons()
    todo = [x for x in sorted(lessons.values(), key=lambda x: x["ts"]) if x["status"] == "proposed"][:PER_TICK]
    done = {"accepted": 0, "rejected": 0}
    for x in todo:
        reason, verdict = "", "rejected"
        if x["call"].get("name") == "ask_owner":
            reason = "yalnızca sahibine soruyordu; lab kendi kararını verir"
        elif not valid_call(x["domain"], x["call"]):
            reason = "çözüm çağrısı geçersiz"
        else:
            ruled = label(x["situation"])
            if ruled and ruled[0] == x["domain"] and ruled[1]["name"] == x["call"]["name"]:
                verdict, reason = "accepted", "sabit kural aynı çözümü gösteriyor"
            else:
                try:
                    if await agree(llm, x):
                        verdict, reason = "accepted", "yeniden sorulduğunda model aynı çözümü verdi"
                    else:
                        reason = "yeniden sorulduğunda model aynı çözümü vermedi"
                except RuntimeError:
                    break  # the model is busy: stop this round, the rest wait
        lessons[x["id"]].update(status=verdict, auto=True, decided_at=time.time(), reason=f"otomatik: {reason}")
        done[verdict] += 1
    if any(done.values()):
        store.save_lessons(lessons)
    log.info("autopilot.decide", **done)
    return done


def export(store: LearningStore, recipes: list[dict[str, Any]]) -> dict[str, Any]:
    """Rebuild lora/sft.jsonl: part recipes (request -> recipe) and accepted lessons (situation -> remedy call)."""
    rows = [
        {"messages": [
            {"role": "user", "content": f"Bu parçanın 3B tarifini (CSG) yaz: {r['text']}"},
            {"role": "assistant", "content": json.dumps(r["recipe"], ensure_ascii=False, sort_keys=True)},
        ]}
        for r in recipes
    ]
    for x in store.lessons().values():
        if x["status"] == "accepted" and x["call"].get("name") != "ask_owner":
            rows.append({"messages": [
                {"role": "user", "content": f"Sorun ({x['domain']}): {x['situation']}"},
                {"role": "assistant", "content": json.dumps(x["call"], ensure_ascii=False, sort_keys=True)},
            ]})
    path = Path(store.root) / "lora" / "sft.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + ("\n" if rows else ""), encoding="utf-8")
    info = {"rows": len(rows), "path": str(path), "at": time.time(), "training": "bekliyor: ana model CPU'da ince ayar yapılamaz; GPU makinesi gerekir"}
    store._write(Path(store.root) / "lora.json", info)  # noqa: SLF001
    return info
