# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Blender boundary tests never require a Blender installation."""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_servers.neml_mcp_blender import server


@pytest.mark.asyncio
async def test_blender_rejects_path_escape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEML_ARTIFACT_DIR", str(tmp_path))
    source = tmp_path / "freecad.stl"
    source.write_bytes(b"stl")
    with pytest.raises(PermissionError):
        await server.render_photo([str(source)], str(tmp_path.parent / "escape.png"))


@pytest.mark.asyncio
async def test_blender_invokes_external_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEML_ARTIFACT_DIR", str(tmp_path))
    source = tmp_path / "freecad.stl"
    source.write_bytes(b"stl")
    output = tmp_path / "photo.png"
    called: list[tuple[list[str], float]] = []

    async def fake_run(argv: list[str], timeout_s: float) -> str:
        called.append((argv, timeout_s))
        output.write_bytes(b"PNG")
        return ""

    monkeypatch.setattr(server, "run_cli", fake_run)
    result = await server.render_photo([str(source)], str(output))
    assert result["kind"] == "photo"
    assert called[0][0][0].endswith("blender")
