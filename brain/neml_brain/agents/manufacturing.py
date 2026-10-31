# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# NEML_SPEC.md 8.2 / 12.4 - manufacturing agent. printer.start is level 4
# (SPEC 5.2) and requires_approval in tools.yaml; Agent.call enforces that in
# code, so no prompt can talk the graph into starting a print.

from typing import Literal

from pydantic import BaseModel, ConfigDict

from neml_brain.agents.base import register


class SliceRequest(BaseModel):
    """Manufacturing is fed an existing artifact, never a language command."""

    model_config = ConfigDict(extra="forbid")

    # SPEC 12.4 - manufacturing/slicer_profiles/*.ini, one per material.
    profile: Literal[
        "petg_0.20_structural",
        "pa6cf_0.20_structural",
        "pla_0.25_draft",
        "asa_0.20_outdoor",
    ]
    artifact_id: str


class PrintJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gcode_path: str | None = None
    preview_png: str | None = None
    duration_h: float | None = None
    filament_g: float | None = None
    layer_count: int | None = None


AGENT = register(
    "manufacturing",
    input_schema=SliceRequest,
    output_schema=PrintJob,
    tools=("db.read", "slicer.slice", "gcode.validate", "printer.status", "printer.start"),
    stages={
        "generate": "slicer.slice",
        "validate": "gcode.validate",
        "execute": "printer.start",
    },
)
