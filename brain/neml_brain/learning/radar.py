# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The lab's radar: public feeds of papers, news, forums and company blogs, read round the clock.

One feed per tick, a few new entries each; every entry's page goes through the Researcher (the
fetch server's allowlist, text as untrusted data, notes only when quoted from the page), so what
the lab learns shows up in its design chat as notes. Only public RSS/Atom feeds: no logins and no
scraping of walled social networks (X, Instagram, LinkedIn); Mastodon tags and forums are public.
"""

from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)

FEEDS: list[tuple[str, str]] = [
    ("arXiv robotik", "https://export.arxiv.org/rss/cs.RO"),
    ("ROS Discourse", "https://discourse.ros.org/latest.rss"),
    ("Hacker News robot", "https://hnrss.org/newest?q=robot+OR+quadruped+OR+gazebo&points=20"),
    ("Hackaday", "https://hackaday.com/blog/feed/"),
    ("IEEE Spectrum robotik", "https://spectrum.ieee.org/feeds/topic/robotics.rss"),
    ("Boston Dynamics", "https://bostondynamics.com/feed/"),
    ("Mastodon #robotics", "https://mastodon.social/tags/robotics.rss"),
    ("Mastodon #quadruped", "https://mastodon.social/tags/quadruped.rss"),
    ("GitHub blog", "https://github.blog/feed/"),
    ("Gazebo", "https://gazebosim.org/blog/feed.xml"),
]
PER_TICK = 3
MAX_SEEN = 3000
ENTRY = re.compile(r"<(?:item|entry)\b.*?</(?:item|entry)>", re.S)
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S)
LINK = re.compile(r"<link[^>]*?href=[\"']([^\"']+)[\"']|<link[^>]*>(.*?)</link>", re.S)


def clean(text: str) -> str:
    text = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", text, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def entries(xml: str) -> list[tuple[str, str]]:
    """(title, link) of every item of an RSS/Atom document."""
    out = []
    for block in ENTRY.findall(xml):
        t, link = TITLE.search(block), LINK.search(block)
        if not (t and link):
            continue
        url = (link.group(1) or link.group(2) or "").strip()
        if url.startswith("https://"):
            out.append((clean(t.group(1))[:160], url))
    return out


class Radar:
    def __init__(self, mcp: Any, researcher: Any, root: Path) -> None:
        self._mcp, self._researcher = mcp, researcher
        self._path = root / "radar.json"
        self._state: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        return {
            "seen": data.get("seen", []),
            "cursor": data.get("cursor", 0),
            "log": data.get("log", []),
            "feeds": data.get("feeds", {}),
        }

    def _save(self) -> None:
        self._state["seen"] = self._state["seen"][-MAX_SEEN:]
        self._state["log"] = self._state["log"][-60:]
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._state, ensure_ascii=False), encoding="utf-8")

    def status(self) -> dict[str, Any]:
        return {
            "feeds": self._state["feeds"],
            "log": list(reversed(self._state["log"]))[:25],
            "seen": len(self._state["seen"]),
        }

    async def tick(self) -> dict[str, Any]:
        """Read the next feed and learn from up to PER_TICK entries not seen before."""
        name, url = FEEDS[self._state["cursor"] % len(FEEDS)]
        self._state["cursor"] += 1
        info: dict[str, Any] = {"at": time.time(), "ok": False, "new": 0, "notes": 0}
        try:
            page = await self._mcp.call("fetch", "fetch", {"url": url}, 40)
            found = entries(str(page.get("text", "")) if isinstance(page, dict) else "")
            info["ok"] = True
        except Exception as exc:  # noqa: BLE001 - a feed that is down or blocks us is reported, not fatal
            info["error"] = str(exc)[:160]
            self._state["feeds"][name] = info
            self._save()
            return {"feed": name, **info}
        seen = set(self._state["seen"])
        for title, link in [e for e in found if e[1] not in seen][:PER_TICK]:
            self._state["seen"].append(link)
            info["new"] += 1
            learned = []
            try:
                got = await self._researcher.learn_pages(f"{name}: {title}", [link])
                learned = got.get("notes", [])
            except Exception as exc:  # noqa: BLE001 - the page may be off the allowlist; the entry is still logged
                log.info("radar.page_skipped", link=link, error=str(exc)[:100])
            info["notes"] += len(learned)
            self._state["log"].append(
                {
                    "at": time.time(),
                    "feed": name,
                    "title": title,
                    "link": link,
                    "notes": len(learned),
                }
            )
        self._state["feeds"][name] = info
        self._save()
        return {"feed": name, **info}
