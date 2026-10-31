# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The background learning loop: notice and propose, one step at a time.

It runs next to the brain. The big model is slow and shared with the owner's chat, so a tick makes
at most one proposal by day and a few at night."""

from __future__ import annotations

from typing import Any

import structlog

from .propose import propose
from .store import LearningStore

log = structlog.get_logger(__name__)


async def tick(store: LearningStore, llm: Any, *, night: bool) -> dict[str, Any]:
    made = 0
    for event in store.unanswered()[: 3 if night else 1]:
        try:
            if await propose(store, llm, event):
                made += 1
        except Exception as exc:  # noqa: BLE001 - the model may be busy; the event stays for the next tick
            log.warning("learning.propose_failed", error=str(exc)[:150])
            break
    return {"proposed": made}
