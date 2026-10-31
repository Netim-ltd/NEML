# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 15 docs/api export (T-017)."""

from __future__ import annotations

import json
from pathlib import Path

import export_openapi


def test_export_writes_every_spec_8_3_path(tmp_path: Path) -> None:
    out = tmp_path / "neml-brain.json"
    export_openapi.export(out)
    schema = json.loads(out.read_text(encoding="utf-8"))

    assert schema["info"]["title"] == "neml-brain"
    # SPEC 8.3 — the endpoint list the operator and the mobile client rely on.
    for path in (
        "/health",
        "/v1/robots",
        "/v1/robots/{robot_id}/estop",
        "/v1/tasks",
        "/v1/command",
        "/v1/skills",
        "/v1/genomes",
        "/v1/campaigns",
        "/v1/approvals/{approval_id}/decide",
        "/v1/telemetry",
        "/v1/sim/run",
        "/v1/budget",
        "/v1/runtime/llm/stop",
    ):
        assert path in schema["paths"], path
