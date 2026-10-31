# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""neml-mcp-fetch: allowlist, redirect re-check, text-only, size cap."""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

import httpx
import pytest

from mcp_servers.neml_mcp_fetch import server


def run(coro: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(coro)


def serve(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        server, "_client", lambda: httpx.AsyncClient(transport=transport, follow_redirects=False)
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://docs.ros.org/a",  # not https
        "https://evil.example.com/a",  # not allowlisted
        "https://docs.ros.org.evil.com/a",  # suffix trick
        "https://user:pw@docs.ros.org/a",  # credentials in the URL
        "https://docs.ros.org:8443/a",  # odd port
        "https://127.0.0.1/a",
        "file:///etc/passwd",
    ],
)
def test_check_url_refuses_everything_off_the_list(url: str) -> None:
    with pytest.raises(server.HostNotAllowed):
        server.check_url(url)


def test_subdomain_of_an_allowed_host_passes() -> None:
    assert server.check_url("https://docs.docs.ros.org/x") == "https://docs.docs.ros.org/x"


def test_html_comes_back_as_inert_text(monkeypatch: pytest.MonkeyPatch) -> None:
    body = "<html><script>alert(1)</script><h1>Gait</h1><p>A &amp; B</p></html>"
    serve(
        monkeypatch,
        lambda r: httpx.Response(200, text=body, headers={"content-type": "text/html"}),
    )
    page = run(server.fetch("https://docs.ros.org/a"))
    assert "alert" not in page.text and "<" not in page.text
    assert "Gait" in page.text and "A & B" in page.text


def test_a_redirect_off_the_allowlist_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(
        monkeypatch,
        lambda r: httpx.Response(302, headers={"location": "https://evil.example.com/x"}),
    )
    with pytest.raises(server.HostNotAllowed):
        run(server.fetch("https://docs.ros.org/a"))


def test_a_redirect_inside_the_allowlist_is_followed(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/a":
            return httpx.Response(301, headers={"location": "/b"})
        return httpx.Response(200, text="ok", headers={"content-type": "text/plain"})

    serve(monkeypatch, handler)
    assert run(server.fetch("https://docs.ros.org/a")).url == "https://docs.ros.org/b"


def test_binaries_and_oversized_bodies_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(
        monkeypatch,
        lambda r: httpx.Response(200, content=b"x", headers={"content-type": "application/zip"}),
    )
    with pytest.raises(server.NotText):
        run(server.fetch("https://docs.ros.org/a"))
    big = b"a" * (server.MAX_BYTES + 1)
    serve(
        monkeypatch,
        lambda r: httpx.Response(200, content=big, headers={"content-type": "text/plain"}),
    )
    with pytest.raises(server.TooLarge):
        run(server.fetch("https://docs.ros.org/a"))


def test_redirect_loop_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, lambda r: httpx.Response(302, headers={"location": "/loop"}))
    with pytest.raises(server.FetchError, match="redirects"):
        run(server.fetch("https://docs.ros.org/loop"))


def test_downloads_stay_under_the_imports_directory_and_obey_the_size_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setattr(server, "DOWNLOAD_ROOT", tmp_path / "imports")
    serve(monkeypatch, lambda r: httpx.Response(200, content=b"abc"))
    done = run(
        server.download(
            "https://raw.githubusercontent.com/o/r/main/a.stl", str(tmp_path / "imports/x/a.stl")
        )
    )
    assert done["bytes"] == 3 and (tmp_path / "imports/x/a.stl").read_bytes() == b"abc"
    with pytest.raises(server.HostNotAllowed):  # outside the imports directory
        run(
            server.download(
                "https://raw.githubusercontent.com/o/r/main/a.stl", str(tmp_path / "evil.stl")
            )
        )
    with pytest.raises(server.HostNotAllowed):  # not a GitHub or documentation host
        run(server.download("https://evil.example.com/a.stl", str(tmp_path / "imports/y.stl")))
    monkeypatch.setattr(server, "MAX_DOWNLOAD_BYTES", 2)
    with pytest.raises(server.TooLarge):
        run(
            server.download(
                "https://raw.githubusercontent.com/o/r/main/a.stl", str(tmp_path / "imports/z.stl")
            )
        )
    assert not (tmp_path / "imports/z.stl").exists()
    assert server.check_url("https://api.github.com/repos/o/r").startswith("https://api.github.com")


def test_the_github_token_goes_to_the_github_api_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEML_GITHUB_TOKEN", "secret-token")
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen[request.url.host] = request.headers.get("authorization")
        return httpx.Response(200, text="{}", headers={"content-type": "application/json"})

    serve(monkeypatch, handler)
    run(server.fetch("https://api.github.com/repos/o/r"))
    run(server.fetch("https://docs.ros.org/a"))
    assert seen == {"api.github.com": "Bearer secret-token", "docs.ros.org": None}
    monkeypatch.delenv("NEML_GITHUB_TOKEN")
    seen.clear()
    run(server.fetch("https://api.github.com/repos/o/r"))
    assert seen == {"api.github.com": None}
