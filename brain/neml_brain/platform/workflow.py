# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic capability-gap design pipeline across existing MCP ports."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from neml_brain.mcp.client import McpClient
from neml_brain.platform.adapters import McpAdapter, SimulationEnvironment, ToolCall
from neml_brain.platform.design import BomLine, CapabilityGap, DesignPackage


@dataclass(frozen=True)
class DesignRecipe:
    mechanical_recipe: dict[
        str, Any
    ]  # a CSG recipe (boxes, cylinders, spheres, cut/fuse) for the CAD MCP
    electrical_circuit: dict[str, Any]  # a circuit recipe for the KiCad MCP
    firmware_path: str
    simulation_scenario: str
    bom: tuple[BomLine, ...]


class VersionControl(Protocol):
    async def commit(self, folder: Path, gap: CapabilityGap) -> str: ...


class GitVersioner:
    """Copy generated files into the dedicated work repository and commit via MCP."""

    def __init__(self, repo_root: Path, client: McpClient) -> None:
        self.repo_root = repo_root.resolve()
        self.client = client

    async def commit(self, folder: Path, gap: CapabilityGap) -> str:
        if not (self.repo_root / ".git").is_dir():
            raise FileNotFoundError("generated-artifact Git repository is not initialized")
        key = hashlib.sha256(
            f"{gap.scope.tenant_id}:{gap.scope.domain_id}:{gap.task_id}".encode()
        ).hexdigest()
        target = self.repo_root / "designs" / key
        target.mkdir(parents=True, exist_ok=True)
        for source in folder.iterdir():
            if source.is_symlink() or not source.is_file():
                raise PermissionError("design package must contain regular files only")
            shutil.copy2(source, target / source.name)
        result = await self.client.call(
            "git", "commit", {"message": f"Add generated design package {key[:16]}"}
        )
        if not isinstance(result, dict) or not result.get("sha"):
            raise RuntimeError("Git MCP returned no commit hash")
        return str(result["sha"])


class DesignWorkflow:
    def __init__(
        self,
        artifact_root: Path,
        freecad: McpAdapter,
        kicad: McpAdapter,
        blender: McpAdapter,
        simulation: SimulationEnvironment,
        firmware_root: Path,
        version_control: VersionControl,
    ) -> None:
        self.artifact_root = artifact_root.resolve()
        self.freecad = freecad
        self.kicad = kicad
        self.blender = blender
        self.simulation = simulation
        self.firmware_root = firmware_root.resolve()
        self.version_control = version_control

    async def create(self, gap: CapabilityGap, recipe: DesignRecipe) -> DesignPackage:
        """Build and validate; no email, print, flash or purchase is triggered."""
        if not gap.required or not recipe.bom:
            raise ValueError("requirements and BOM are mandatory")
        cost = sum((line.unit_usd * line.quantity for line in recipe.bom), Decimal(0))
        if cost >= Decimal("50.00"):
            raise PermissionError("first physical prototype exceeds 50 USD parts cap")
        firmware = Path(recipe.firmware_path).resolve()
        if self.firmware_root not in firmware.parents or not firmware.is_file():
            raise FileNotFoundError("reviewed firmware template is required")
        key = hashlib.sha256(
            f"{gap.scope.tenant_id}:{gap.scope.domain_id}:{gap.task_id}".encode()
        ).hexdigest()
        folder = self.artifact_root / "designs" / key
        folder.mkdir(parents=True, exist_ok=True)
        copied_firmware = folder / firmware.name
        shutil.copy2(firmware, copied_firmware)
        request_hash = hashlib.sha256(
            json.dumps(recipe.mechanical_recipe, sort_keys=True).encode()
        ).hexdigest()
        cad = await self.freecad.invoke(
            ToolCall(gap.scope, "freecad", "build_recipe", request_hash, 120),
            {"recipe": recipe.mechanical_recipe, "out_dir": str(folder), "name": "part"},
        )
        files = [Path(path).resolve() for path in (cad.get("step"), cad.get("stl")) if path]
        if not files or any(folder not in path.parents or not path.is_file() for path in files):
            raise ValueError("FreeCAD returned no valid design files")
        source_cad = next((path for path in files if path.suffix.lower() == ".step"), None)
        stl = next((path for path in files if path.suffix.lower() == ".stl"), None)
        if source_cad is None or stl is None:
            raise ValueError("the STEP source and the STL export are both required")
        electrical = await self.kicad.invoke(
            ToolCall(gap.scope, "kicad", "build_circuit", request_hash, 180),
            {"circuit": recipe.electrical_circuit, "out_dir": str(folder), "name": "board"},
        )
        schematic = Path(electrical["schematic"]).resolve()
        board = Path(electrical["board"]).resolve()
        if any(folder not in path.parents or not path.is_file() for path in (schematic, board)):
            raise ValueError("KiCad artifacts are outside the design folder")
        erc = await self.kicad.invoke(
            ToolCall(gap.scope, "kicad", "run_erc", request_hash, 180),
            {"schematic_path": str(schematic)},
        )
        drc = await self.kicad.invoke(
            ToolCall(gap.scope, "kicad", "run_drc", request_hash, 180),
            {"board_path": str(board)},
        )
        if erc.get("passed") is not True or drc.get("passed") is not True:
            raise PermissionError("KiCad ERC/DRC did not pass")
        sim = await self.simulation.run(gap.scope, recipe.simulation_scenario, key)
        if sim.get("success", 0) < 0.9 or sim.get("safety_violation", 1) != 0:
            raise PermissionError("design failed simulation gate")
        requirements = folder / "requirements.md"
        requirements.write_text(
            "# Robot design requirements\n\n"
            f"Task: {gap.task_id}\n\n"
            f"Required capabilities: {', '.join(sorted(gap.required))}\n\n"
            f"Gap: {gap.reason}\n",
            encoding="utf-8",
        )
        sim_report = folder / "simulation.json"
        sim_report.write_text(json.dumps(sim, sort_keys=True), encoding="utf-8")
        for operation, output in (
            ("render_photo", "photo.png"),
            ("render_video", "video.mp4"),
            ("animate_assembly", "assembly.mp4"),
        ):
            await self.blender.invoke(
                ToolCall(gap.scope, "blender", operation, request_hash, 600),
                {"sources": [str(stl)], "output": str(folder / output)},
            )
        commit = await self.version_control.commit(folder, gap)
        return DesignPackage(
            gap,
            str(requirements),
            str(source_cad),
            str(board),
            str(copied_firmware),
            str(sim_report),
            recipe.bom,
            version_commit=commit,
        )
