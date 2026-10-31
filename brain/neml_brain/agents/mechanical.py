# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# NEML_SPEC.md 8.2 - mechanical agent. There are no parametric templates: its output schema IS the
# guided_json schema of a CSG recipe (boxes, cylinders, spheres, cut/fuse) that the CAD MCP draws in
# FreeCAD. PARAM_FILL feeds model_json_schema() to the model, so a value outside these bounds is not
# merely rejected, it is undecodable; the CAD server validates the recipe again as data.

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from neml_brain.agents.base import DesignRequest, register

Pos = Annotated[float, Field(ge=-600, le=600)]
Size = Annotated[float, Field(ge=0.1, le=600)]


class Solid(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=12)
    t: Literal["box", "cyl", "sphere"]
    at: list[Pos] = Field(min_length=3, max_length=3)  # corner (box), base centre (cyl), centre
    size: list[Size] | None = Field(default=None, min_length=3, max_length=3)
    r: float | None = Field(default=None, ge=0.1, le=600)
    h: float | None = Field(default=None, ge=0.1, le=600)
    axis: Literal["x", "y", "z"] | None = None


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["cut", "fuse"]
    a: str = Field(max_length=12)
    b: str = Field(max_length=12)
    out: str = Field(max_length=12)


class Recipe(BaseModel):
    model_config = ConfigDict(extra="forbid")

    solids: list[Solid] = Field(min_length=1, max_length=30)
    steps: list[Step] = Field(default_factory=list, max_length=30)
    result: str = Field(max_length=12)


class MechChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    part_name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    recipe: Recipe
    rationale: str | None = Field(default=None, max_length=300)


# SPEC 5.4 grants [db.read, cad.generate, cad.export, sim.run] and forbids
# printer.*, firmware.*, kicad.order - register() checks that here, at import.
AGENT = register(
    "mechanical",
    input_schema=DesignRequest,
    output_schema=MechChange,
    tools=("db.read", "cad.generate", "cad.export", "sim.run"),
    stages={"generate": "cad.generate", "simulate": "sim.run", "execute": "cad.export"},
)
