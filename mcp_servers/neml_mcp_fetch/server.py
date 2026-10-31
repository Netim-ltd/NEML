# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""neml-mcp-fetch - allowlist-only web fetch, port 9109 (SPEC 6.1 #7).

Documentation pages for the agents, nothing else. Three fences, all enforced
here and not by asking a model nicely (SPEC 5.4):

* https only, and the host must be an allowlisted name or a subdomain of one;
* every redirect hop is re-checked against the same allowlist, so an allowed
  page cannot bounce the daemon to an arbitrary host;
* the body is capped, and what comes back is *text*, never HTML or script.

The text is untrusted input. The brain wraps it in <untrusted_data> before any
prompt sees it (SPEC 5.4); this server only makes it small and inert.
"""

from __future__ import annotations

import hashlib
import html
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from mcp_servers._common import make_app

PORT = 9109
VERSION = "1.0.0"
# SPEC 6.1 #7 / mcp_servers/vendor/servers.yaml `fetch.allowlist`.
DEFAULT_ALLOWLIST = (
    "docs.ros.org",
    "gazebosim.org",
    "wiki.freecad.org",
    "docs.kicad.org",
    "help.prusa3d.com",
    "docs.vllm.ai",
    "www.postgresql.org",
    # design knowledge for the model chat: biomechanics, robot-leg papers and part documentation
    "en.wikipedia.org",
    "arxiv.org",
    "raw.githubusercontent.com",
    "emanual.robotis.com",
    # open-source designs the operator imports: repository metadata and raw files
    "api.github.com",
    # the lab's radar: public feeds of papers, news, forums and company blogs (no logins, no scraping of walled social media)
    "export.arxiv.org",
    "hnrss.org",
    "discourse.ros.org",
    "hackaday.com",
    "spectrum.ieee.org",
    "bostondynamics.com",
    "www.unitree.com",
    "www.anybotics.com",
    "robotis.com",
    "mastodon.social",
    "github.blog",
    "ros.org",
    "openrobotics.org",
    # Turkish electronics shops: the board team checks whether a part can be bought in Turkey
    "www.robotistan.com",
    "www.direnc.net",
    "www.robo90.com",
    "gazebosim.org",
)
MAX_BYTES = 3 * 1024 * 1024  # shop pages are heavy HTML; the text that comes out is cut small by the caller
MAX_REDIRECTS = 3
DEFAULT_TIMEOUT_S = 20.0
TEXT_TYPES = (
    "text/html",
    "text/plain",
    "application/xhtml+xml",
    "text/markdown",
    "application/json",
    "application/rss+xml",
    "application/atom+xml",
    "application/xml",
    "text/xml",
)
DOWNLOAD_ROOT = Path(os.environ.get("NEML_DOWNLOAD_ROOT", "/srv/neml/artifacts/imports"))
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024


class FetchError(RuntimeError):
    """Base typed error (SPEC 6.3)."""


class HostNotAllowed(FetchError):
    """Not https, or the host is not on the allowlist."""


class NotText(FetchError):
    """Only documentation text is served, never binaries."""


class TooLarge(FetchError):
    """Body past the cap. Refused rather than truncated silently."""


@dataclass
class Page:
    url: str
    status: int
    content_type: str
    text: str


def _allowlist() -> tuple[str, ...]:
    raw = os.environ.get("NEML_FETCH_ALLOWLIST")
    if not raw:
        return DEFAULT_ALLOWLIST
    return tuple(h.strip().lower() for h in raw.split(",") if h.strip())


def check_url(url: str) -> str:
    """Return the normalised URL, or raise HostNotAllowed. The single gate."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or parts.username or parts.password:
        raise HostNotAllowed(f"only plain https URLs are fetched, got '{url}'")
    if parts.port not in (None, 443):
        raise HostNotAllowed("only port 443 is fetched")
    if not any(host == allowed or host.endswith("." + allowed) for allowed in _allowlist()):
        raise HostNotAllowed(f"'{host}' is not on the fetch allowlist")
    return parts.geturl()


_SCRIPT = re.compile(r"<(script|style|noscript)\b.*?</\1\s*>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")
_BLANKS = re.compile(r"\n\s*\n\s*\n+")


def to_text(body: str, content_type: str) -> str:
    """HTML -> readable text. Scripts and styles go first, then every tag."""
    if "html" not in content_type:
        return body.strip()
    stripped = _TAG.sub("\n", _SCRIPT.sub(" ", body))
    return _BLANKS.sub("\n\n", html.unescape(stripped)).strip()


def _headers(url: str) -> dict[str, str]:
    """GitHub allows 60 anonymous API calls an hour; NEML_GITHUB_TOKEN raises that to 5000.

    It is sent to api.github.com only, never to another host a redirect might name.
    """
    token = os.environ.get("NEML_GITHUB_TOKEN", "").strip()
    if token and (urlsplit(url).hostname or "") == "api.github.com":
        return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    return {}


def _client() -> httpx.AsyncClient:
    # Redirects are followed by hand below so each hop is checked.
    return httpx.AsyncClient(follow_redirects=False, timeout=DEFAULT_TIMEOUT_S)


async def fetch(url: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> Page:
    """GET one allowlisted documentation page and return it as text."""
    current = check_url(url)
    async with _client() as client:
        for _ in range(MAX_REDIRECTS + 1):
            async with client.stream(
                "GET", current, timeout=timeout_s, headers=_headers(current)
            ) as response:
                if response.is_redirect:
                    location = response.headers.get("location", "")
                    current = check_url(urljoin(current, location))  # re-gate every hop
                    continue
                ctype = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if ctype not in TEXT_TYPES:
                    raise NotText(f"'{ctype or 'unknown'}' is not documentation text")
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw += chunk
                    if len(raw) > MAX_BYTES:
                        raise TooLarge(f"body exceeds {MAX_BYTES} bytes")
                text = to_text(bytes(raw).decode(response.encoding or "utf-8", "replace"), ctype)
                return Page(current, response.status_code, ctype, text)
    raise FetchError(f"more than {MAX_REDIRECTS} redirects")


async def download(url: str, dest: str, timeout_s: float = 60.0) -> dict[str, Any]:
    """GET one allowlisted file (a model, a board) into the imports directory; nothing else.

    Same fences as `fetch` (https, allowlisted host, every redirect re-checked) plus a size cap;
    the destination must sit under DOWNLOAD_ROOT. The bytes are written, never interpreted.
    """
    target = Path(dest).resolve()
    root = DOWNLOAD_ROOT.resolve()
    if root not in target.parents:
        raise HostNotAllowed(f"downloads go under {root}")
    current = check_url(url)
    target.parent.mkdir(parents=True, exist_ok=True)
    async with _client() as client:
        for _ in range(MAX_REDIRECTS + 1):
            async with client.stream("GET", current, timeout=timeout_s) as response:
                if response.is_redirect:
                    current = check_url(urljoin(current, response.headers.get("location", "")))
                    continue
                if response.status_code != 200:
                    raise FetchError(f"HTTP {response.status_code} for {current}")
                digest, size, too_big = hashlib.sha256(), 0, False
                with target.open("wb") as out:
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_DOWNLOAD_BYTES:
                            too_big = True
                            break
                        digest.update(chunk)
                        out.write(chunk)
                if too_big:
                    target.unlink(missing_ok=True)
                    raise TooLarge(f"file exceeds {MAX_DOWNLOAD_BYTES} bytes")
                return {"path": str(target), "bytes": size, "sha256": digest.hexdigest()}
    raise FetchError(f"more than {MAX_REDIRECTS} redirects")


def allowlist() -> list[str]:
    """The hosts this daemon will serve."""
    return list(_allowlist())


TOOLS: dict[str, Callable[..., Any]] = {
    "fetch": fetch,
    "allowlist": allowlist,
    "download": download,
}

app = make_app("neml-mcp-fetch", VERSION, TOOLS)

if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT)
