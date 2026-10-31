# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Turn an observed problem into a proposed lesson (cause + one remedy call) for the owner to accept.

The area's own small model answers first when there is one and it is sure; the big model is asked
only otherwise (it is slow on this CPU). Either way the answer is checked against the remedy's
schema, and nothing is applied: an accepted lesson becomes training data and a hint.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

import jsonschema

from .domains import DOMAINS
from .store import LearningStore

PROMPT = (
    "Bir robot laboratuvarında şu sorun görüldü ({domain}): {text}\n"
    "Bağlam: {context}\n"
    "Kısa bir neden (cause) ve tek bir çözüm çağrısı (call) yaz. Çözüm şu araçlardan biri olmalı: {tools}. "
    "Emin değilsen ask_owner seç."
)


AUTO_CONFIDENCE = 0.9


def auto_enabled() -> bool:
    """Self-driving mode: consistent proposals are accepted by the lab itself (NEML_LEARNING_AUTO=false turns it off)."""
    return os.environ.get("NEML_LEARNING_AUTO", "true").lower() != "false"


PROMPT2 = (
    "Sorun: {text}\n"
    "Alan: {domain}. Kullanılabilir çözüm araçları: {tools}.\n"
    "Bu sorunu gidermek için tek bir araç çağrısı seç ve nedenini kısaca yaz; belirsizse ask_owner seç."
)


def valid_call(domain: str, call: Any) -> bool:
    if not isinstance(call, dict):
        return False
    for tool in DOMAINS[domain]["tools"]:
        if tool["name"] == call.get("name"):
            try:
                jsonschema.validate(call.get("arguments", {}), tool["parameters"])
            except jsonschema.ValidationError:
                return False
            return True
    return False


def schema(domain: str) -> dict[str, Any]:
    names = [t["name"] for t in DOMAINS[domain]["tools"]]
    return {
        "type": "object",
        "properties": {
            "cause": {"type": "string", "maxLength": 300},
            "call": {
                "type": "object",
                "properties": {"name": {"enum": names}, "arguments": {"type": "object"}},
                "required": ["name", "arguments"],
            },
        },
        "required": ["cause", "call"],
    }


async def propose(store: LearningStore, llm: Any, event: dict[str, Any]) -> dict[str, Any] | None:
    """One lesson for one event, stored as `proposed`; None when nothing sensible came out."""
    domain, text = event["domain"], event["text"]
    agreed = False
    names = ", ".join(t["name"] for t in DOMAINS[domain]["tools"])
    prompt = PROMPT.format(
        domain=DOMAINS[domain]["label"],
        text=text,
        context=str(event.get("context", {}))[:400],
        tools=names,
    )
    out = await llm.fill(prompt, schema(domain), profile="param_skill")
    if not valid_call(domain, out.get("call")):
        return None
    cause, call = str(out.get("cause", ""))[:300], out["call"]
    if auto_enabled() and call["name"] != "ask_owner":
        # self-consistency: the same remedy twice in a row is accepted without the owner
        second = PROMPT2.format(text=text, domain=DOMAINS[domain]["label"], tools=names)  # worded differently on purpose
        again = await llm.fill(second, schema(domain), profile="param_skill")
        agreed = valid_call(domain, again.get("call")) and again["call"] == call
    lesson = {
        "id": uuid.uuid4().hex[:12],
        "fp": event["fp"],
        "domain": domain,
        "kind": event["kind"],
        "situation": text,
        "cause": cause,
        "call": call,
        "source": "llm",
        "confidence": None,
        "status": "accepted" if agreed else "proposed",
        "auto": agreed,
        "ts": time.time(),
        **({"decided_at": time.time()} if agreed else {}),
    }
    lessons = store.lessons()
    lessons[lesson["id"]] = lesson
    store.save_lessons(lessons)
    return lesson


def shown(store: LearningStore, domain: str, limit: int = 5) -> list[dict[str, Any]]:
    """The accepted lessons a prompt gets: the ones that measurably helped first, then the newest."""
    rows = store.accepted(domain)
    return sorted(rows, key=lambda x: (not x.get("proven"), -x.get("decided_at", 0)))[:limit]


def hints(store: LearningStore, domain: str, limit: int = 5) -> str:
    """Accepted lessons as a few lines for a prompt ("what the lab learned here")."""
    return chr(10).join(
        f"- {x['situation']} -> {x['call']['name']}({x['call']['arguments']})"
        for x in shown(store, domain, limit)
    )
