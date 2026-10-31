# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Executed by Blender's Python interpreter, never imported by neml-brain."""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import bpy  # type: ignore[import-not-found]
from mathutils import Vector  # type: ignore[import-not-found]


def main() -> None:
    request = json.loads(Path(sys.argv[-1]).read_text(encoding="utf-8"))
    sources = request["sources"]
    output = request["output"]
    kind = request["kind"]
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    parts: list[Any] = []
    for source in sources:
        before = set(bpy.data.objects)
        bpy.ops.wm.stl_import(filepath=source)
        parts.extend(obj for obj in bpy.data.objects if obj not in before)
    if not parts:
        raise RuntimeError("no FreeCAD geometry imported")
    for part in parts:
        part.data.materials.clear()
        material = bpy.data.materials.new(name="NEML metal")
        material.diffuse_color = (0.2, 0.45, 0.7, 1)
        part.data.materials.append(material)
    corners = [part.matrix_world @ Vector(corner) for part in parts for corner in part.bound_box]
    lower = Vector(tuple(min(c[axis] for c in corners) for axis in range(3)))
    upper = Vector(tuple(max(c[axis] for c in corners) for axis in range(3)))
    center = (lower + upper) / 2
    radius = max((upper - lower).length, 1.0)
    bpy.ops.object.camera_add(location=center + Vector((1.5, -2.0, 1.2)) * radius)
    camera = bpy.context.object
    direction = center - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    camera.data.clip_end = max(camera.data.clip_end, radius * 20)
    bpy.context.scene.camera = camera
    bpy.ops.object.light_add(type="AREA", location=center + Vector((2, -3, 4)) * radius)
    bpy.context.object.data.energy = 1000 * radius
    scene = bpy.context.scene
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    # Knobs for hosts without a GPU: a smaller frame and every Nth frame of the same orbit.
    scene.render.resolution_percentage = int(os.environ.get("NEML_RENDER_PERCENT", "100"))
    scene.render.filepath = output
    if kind == "photo":
        scene.render.image_settings.file_format = "PNG"
        bpy.ops.render.render(write_still=True)
        return
    scene.frame_start = 1
    scene.frame_end = 120
    scene.render.fps = 24
    scene.frame_step = int(os.environ.get("NEML_RENDER_FRAME_STEP", "1"))
    if kind == "assembly_animation":
        for index, part in enumerate(parts):
            final = part.location.copy()
            part.location = final + Vector((0, 0, radius * 0.35 * (index + 1)))
            part.keyframe_insert(data_path="location", frame=1)
            part.location = final
            part.keyframe_insert(data_path="location", frame=min(110, 45 + index * 5))
    elif kind == "video":
        for frame in (1, 31, 61, 91, 120):
            angle = 2 * math.pi * (frame - 1) / 119
            camera.location = center + Vector(
                (
                    2.5 * math.cos(angle) * radius,
                    2.5 * math.sin(angle) * radius,
                    1.2 * radius,
                )
            )
            camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
            camera.keyframe_insert(data_path="location", frame=frame)
            camera.keyframe_insert(data_path="rotation_euler", frame=frame)
    else:
        raise ValueError("unsupported media kind")
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    bpy.ops.render.render(animation=True)


if __name__ == "__main__":
    main()
