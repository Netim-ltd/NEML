# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# NEML_SPEC.md 8.2 / 13.1 - electronics agent. The output schema encodes the SPEC 13.1 scope limit
# directly: 2 layers, >=0603, <10 MHz, <=10 A, <=48 V. Anything outside that class uses an
# off-the-shelf module and never reaches this agent.

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from neml_brain.agents.base import DesignRequest, register


class Part(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: str = Field(pattern=r"^[A-Z]{1,3}[0-9]{1,3}$")
    value: str = Field(max_length=30)
    kind: Literal["R", "C", "L", "D", "LED", "IC", "CONN", "MOD", "SW", "Q", "F"]
    package: Literal["0603", "0805", "1206", "2512", "THT"] = (
        "0603"  # SPEC 13.1: nothing under 0603
    )
    pins: list[list[str]] = Field(
        min_length=1, max_length=40
    )  # [number, name, electrical type, net]
    part_number: str | None = Field(default=None, max_length=40)
    decouples: str | None = Field(default=None, max_length=6)
    needs_decoupling: list[str] = Field(default_factory=list, max_length=4)


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_current_a: float | None = Field(default=None, ge=0, le=10)  # SPEC 13.1: >10 A forbidden
    max_voltage_v: float | None = Field(default=None, ge=0, le=48)
    max_digital_mhz: float | None = Field(default=None, ge=0, lt=10)


class Circuit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(max_length=60)
    parts: list[Part] = Field(min_length=2, max_length=60)
    track_mm: float | None = Field(default=None, ge=0.15, le=1.0)
    limits: Limits | None = None


class ElecChange(BaseModel):
    """A board described as data: the KiCad MCP draws, places and routes it (no templates)."""

    model_config = ConfigDict(extra="forbid")

    board_name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,40}$")
    circuit: Circuit
    rationale: str | None = Field(default=None, max_length=300)


# SPEC 5.4: kicad.gerber_export is requires_approval, so Agent.call refuses it
# without an approval id - the SPEC 13.2 "human review cannot be skipped" gate.
AGENT = register(
    "electronics",
    input_schema=DesignRequest,
    output_schema=ElecChange,
    tools=("db.read", "kicad.generate", "kicad.drc", "kicad.bom", "kicad.gerber_export"),
    stages={
        "generate": "kicad.generate",
        "validate": "kicad.drc",
        "execute": "kicad.gerber_export",
    },
)
