# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Restricted Blender MCP server for FreeCAD export media only."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from mcp_servers._common import make_app, run_cli

PORT = 9110
VERSION = "1.0.0"
DRIVER = Path(__file__).with_name("driver.py")
KINDS = frozenset({"photo", "video", "assembly_animation"})


def _within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _paths(sources: list[str], output: str, kind: str) -> tuple[list[Path], Path]:
    if kind not in KINDS or not sources or len(sources) > 32:
        raise ValueError("unsupported media request")
    artifact_root = Path(os.environ["NEML_ARTIFACT_DIR"]).resolve()
    inputs = [Path(item).resolve() for item in sources]
    target = Path(output).resolve()
    if any(not _within(item, artifact_root) or item.suffix.lower() != ".stl" for item in inputs):
        raise PermissionError("media input must be a FreeCAD STL artifact")
    if any(not item.is_file() for item in inputs):
        raise FileNotFoundError("FreeCAD source artifact missing")
    suffix = ".png" if kind == "photo" else ".mp4"
    if not _within(target, artifact_root) or target.suffix.lower() != suffix:
        raise PermissionError("media output must stay in the artifact directory")
    return inputs, target


async def render(
    sources: list[str], output: str, kind: str, timeout_s: float = 600.0
) -> dict[str, Any]:
    """Create a presentation photo, video, or assembly animation from FreeCAD STL exports."""
    inputs, target = _paths(sources, output, kind)
    if not 0 < timeout_s <= 900:
        raise ValueError("timeout out of range")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="neml_blender_") as directory:
        request = Path(directory) / "request.json"
        request.write_text(
            json.dumps(
                {"sources": [str(item) for item in inputs], "output": str(target), "kind": kind}
            ),
            encoding="utf-8",
        )
        await run_cli(
            [
                os.getenv("BLENDER_BIN", "blender"),
                "-b",
                "--python",
                str(DRIVER),
                "--",
                str(request),
            ],
            timeout_s,
        )
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError("Blender produced no media file")
    return {"path": str(target), "kind": kind, "size_bytes": target.stat().st_size}


async def render_photo(sources: list[str], output: str, timeout_s: float = 600.0) -> dict[str, Any]:
    """Render a PNG product photograph from FreeCAD geometry."""
    return await render(sources, output, "photo", timeout_s)


async def render_video(sources: list[str], output: str, timeout_s: float = 600.0) -> dict[str, Any]:
    """Render an MP4 product presentation from FreeCAD geometry."""
    return await render(sources, output, "video", timeout_s)


async def animate_assembly(
    sources: list[str], output: str, timeout_s: float = 600.0
) -> dict[str, Any]:
    """Render an MP4 assembly sequence from FreeCAD geometry."""
    return await render(sources, output, "assembly_animation", timeout_s)


app = make_app(
    "neml-mcp-blender",
    VERSION,
    {
        "render_photo": render_photo,
        "render_video": render_video,
        "animate_assembly": animate_assembly,
    },
)

if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT)
