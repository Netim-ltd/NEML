# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Recordings of simulation runs: annotated GIFs, and getting them to the cloud panel.

The panel lives on another host and the lab is never reachable from it, so a recording is
pushed out: the lab uploads the file to the API (bridge key, same as the websocket) and the
candidate or task row carries the returned URL.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageDraw

WIDTH = 640  # frames are enlarged (nearest-neighbour) to about this width for the panel
MAX_BYTES = 8 * 1024 * 1024
CONTENT_TYPES = {
    "gif": "image/gif",
    "png": "image/png",
    "stl": "model/stl",
    "step": "model/step",
    "svg": "image/svg+xml",
    "dxf": "image/vnd.dxf",
    "nmesh": "application/x-neml-mesh",
    "csv": "text/csv",
    "kicad_sch": "text/plain",
    "kicad_pcb": "text/plain",
    "json": "application/json",
}  # the API refuses more; a recording that large is a bug


@dataclass(frozen=True)
class Frame:
    image: Image.Image
    t_s: float
    x_m: float
    note: str = ""


def annotate(frame: Frame, label: str, goal_x_m: float = 1.0) -> Image.Image:
    """The camera frame, enlarged, with a caption bar: label, sim time, distance and progress."""
    scale = max(1, WIDTH // frame.image.width)
    image = frame.image.convert("RGB").resize(
        (frame.image.width * scale, frame.image.height * scale), Image.Resampling.NEAREST
    )
    bar = 34
    canvas = Image.new("RGB", (image.width, image.height + bar), (16, 20, 20))
    canvas.paste(image, (0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (6, image.height + 4), f"{label}  t={frame.t_s:.1f}s  x={frame.x_m:.2f} m", fill="white"
    )
    progress = max(0.0, min(1.0, frame.x_m / goal_x_m if goal_x_m else 0.0))
    top = image.height + bar - 9
    draw.rectangle((6, top, image.width - 6, top + 5), outline=(90, 110, 110))
    draw.rectangle((6, top, 6 + int((image.width - 12) * progress), top + 5), fill=(130, 215, 200))
    return canvas


def build_gif(frames: Sequence[Frame], label: str, out: Path, goal_x_m: float = 1.0) -> Path:
    """Write the run as a looping GIF. Needs at least one frame."""
    if not frames:
        raise ValueError("a recording needs at least one frame")
    images = [annotate(f, label, goal_x_m) for f in frames]
    out.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(
        out,
        save_all=True,
        append_images=images[1:],
        duration=400,
        loop=0,
        optimize=True,
    )
    return out


def read_frame(path: str | Path) -> Image.Image:
    """The plugin writes PPM; Pillow opens it and the file is detached from the disk."""
    with Image.open(path) as opened:
        return opened.copy()


def blank_frame(width: int = 160, height: int = 120) -> Image.Image:
    return Image.new("RGB", (width, height), (40, 44, 44))


class MediaUploader:
    """Pushes a file to the cloud API's media store; returns the URL path the panel uses."""

    def __init__(self, base_url: str, api_key: str, node_id: str, timeout_s: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {"X-NEML-Key": api_key, "X-NEML-Node": node_id}
        self.timeout_s = timeout_s

    @classmethod
    def from_ws_url(cls, ws_url: str, api_key: str, node_id: str) -> MediaUploader:
        """wss://host/bridge/ws -> https://host (ws:// -> http:// for the in-network API)."""
        base = ws_url.replace("wss://", "https://", 1).replace("ws://", "http://", 1)
        return cls(base.split("/bridge/", 1)[0], api_key, node_id)

    async def upload(self, path: Path, kind: str = "gif", name: str | None = None) -> str | None:
        """None on any failure: a missing recording must never fail a run.

        The default name is the content hash, so a URL never changes meaning. A scene is the one
        exception: it is replaced in place, under a name the API can derive from the genome id.
        """
        data = path.read_bytes()
        if len(data) > MAX_BYTES:
            return None
        name = name or hashlib.sha256(data).hexdigest()[:24] + path.suffix
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as http:
                response = await http.put(
                    f"{self.base_url}/bridge/media/{name}",
                    content=data,
                    headers={
                        **self.headers,
                        "Content-Type": CONTENT_TYPES.get(kind, "application/octet-stream"),
                    },
                )
            response.raise_for_status()
            url: str = response.json()["url"]
            return url
        except (httpx.HTTPError, KeyError, ValueError):
            return None


def gif_bytes(frames: Sequence[Frame], label: str) -> bytes:
    """In-memory variant, used by tests."""
    buffer = io.BytesIO()
    images = [annotate(f, label) for f in frames]
    images[0].save(buffer, format="GIF", save_all=True, append_images=images[1:], duration=400)
    return buffer.getvalue()


def live_name(model: str) -> str:
    """The panel's 'live frame' file of a model, replaced in place on every frame."""
    return "live-" + hashlib.sha256(model.encode()).hexdigest()[:12] + ".png"


def media_entry(kind: str, url: str, caption: str) -> dict[str, Any]:
    return {"kind": kind, "url": url, "caption": caption}
