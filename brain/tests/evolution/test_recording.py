# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Recordings: annotated GIF frames and the media upload."""

from __future__ import annotations

import httpx
import pytest
from PIL import Image

from neml_brain.evolution.recording import (
    Frame,
    MediaUploader,
    annotate,
    blank_frame,
    build_gif,
)


def frames(n: int = 3) -> list[Frame]:
    return [Frame(blank_frame(), 0.5 * (i + 1), 0.2 * i) for i in range(n)]


def test_a_gif_has_one_frame_per_step_and_is_larger_than_the_camera_image(tmp_path):
    out = build_gif(frames(4), "flat", tmp_path / "run.gif")
    with Image.open(out) as gif:
        assert gif.n_frames == 4
        assert gif.width == 640 and gif.height > 480  # enlarged, plus the caption bar


def test_the_caption_bar_is_drawn_and_progress_is_clamped():
    plain = annotate(Frame(blank_frame(), 1.0, 5.0), "flat", goal_x_m=1.0)
    assert plain.getpixel((20, plain.height - 6)) == (130, 215, 200)  # bar full, not overflowing


def test_a_recording_without_frames_is_refused(tmp_path):
    with pytest.raises(ValueError, match="at least one frame"):
        build_gif([], "x", tmp_path / "x.gif")


def test_the_uploader_derives_the_api_address_from_the_websocket_url():
    up = MediaUploader.from_ws_url("ws://api:8080/bridge/ws", "k", "lab-01")
    assert up.base_url == "http://api:8080"
    assert (
        MediaUploader.from_ws_url("wss://h.example/bridge/ws", "k", "n").base_url
        == "https://h.example"
    )


async def test_an_upload_returns_the_url_and_a_failure_returns_none(tmp_path, monkeypatch):
    path = build_gif(frames(), "flat", tmp_path / "run.gif")
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["key"] = str(request.url), request.headers["X-NEML-Key"]
        return httpx.Response(200, json={"url": "/api/v1/media/abc.gif"})

    real = httpx.AsyncClient

    def client(**kw):
        return real(transport=httpx.MockTransport(handler), **kw)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    up = MediaUploader("http://api:8080", "secret", "lab-01")
    assert await up.upload(path) == "/api/v1/media/abc.gif"
    assert seen["key"] == "secret" and str(seen["url"]).startswith("http://api:8080/bridge/media/")

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(500)), **kw),
    )
    assert await up.upload(path) is None
