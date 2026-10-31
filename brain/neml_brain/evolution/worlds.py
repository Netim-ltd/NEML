# ruff: noqa: E501, S311
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Worlds the lab designs for itself: parametric Gazebo scenes (a hobby garden, a warehouse, a
stair hall) written as SDF under the SPEC 11.1 physics contract, checked before they go live.

A world is only used after `check` passes: valid XML, the contract's physics and plugins, no
remote assets (SPEC 11.2 determinism), a clear spawn zone and a path a robot of this size can
actually walk from the spawn to the goal (breadth-first search on an occupancy grid). Generated
worlds are plain files in `<artifacts>/worlds`; the sim server falls back to that folder.
"""

from __future__ import annotations

import json
import math
import os
import random
import xml.etree.ElementTree as ET  # noqa: S405 - our own generated text
from collections import deque
from pathlib import Path
from typing import Any

BUILTIN = ("flat", "maze", "obstacle_low", "ramp_10deg", "rough_terrain")
TEMPLATES = ("hobby_garden", "warehouse", "stair_hall")
STEP_LIMIT_M = 0.04  # what the small quadruped can step over; taller is a wall
ROBOT_RADIUS_M = 0.18
GOAL = (3.0, 0.0)
CELL = 0.05

HEAD = """<?xml version="1.0"?>
<sdf version="1.10">
  <world name="{name}">
    <physics name="dart_1ms" type="dart">
      <max_step_size>0.001</max_step_size>
      <real_time_factor>0</real_time_factor>
    </physics>
    <plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics">
      <engine><filename>gz-physics-dartsim-plugin</filename></engine>
    </plugin>
    <plugin filename="gz-sim-user-commands-system" name="gz::sim::systems::UserCommands"/>
    <plugin filename="gz-sim-scene-broadcaster-system" name="gz::sim::systems::SceneBroadcaster"/>
    <plugin filename="gz-sim-sensors-system" name="gz::sim::systems::Sensors"><render_engine>ogre2</render_engine></plugin>
    <plugin filename="gz-sim-imu-system" name="gz::sim::systems::Imu"/>
    <plugin filename="gz-sim-contact-system" name="gz::sim::systems::Contact"/>
    <plugin filename="NemlSystem" name="neml::NemlSystem"/>
    <plugin filename="gz-sim-joint-state-publisher-system" name="gz::sim::systems::JointStatePublisher"/>
    <gravity>0 0 -9.8</gravity>
    <scene><ambient>0.4 0.4 0.4 1</ambient><background>0.7 0.7 0.7 1</background><shadows>false</shadows></scene>
    <light type="directional" name="sun">
      <cast_shadows>false</cast_shadows><pose>0 0 10 0 0 0</pose>
      <diffuse>0.8 0.8 0.8 1</diffuse><specular>0.2 0.2 0.2 1</specular><direction>-0.5 0.1 -0.9</direction>
    </light>
    <model name="ground_plane"><static>true</static><link name="link">
      <collision name="collision"><geometry><plane><normal>0 0 1</normal><size>100 100</size></plane></geometry>
        <surface><friction><ode><mu>{mu}</mu><mu2>{mu}</mu2></ode></friction></surface></collision>
      <visual name="visual"><geometry><plane><normal>0 0 1</normal><size>100 100</size></plane></geometry>
        <material><ambient>{ground}</ambient><diffuse>{ground}</diffuse></material></visual>
    </link></model>
"""


def box(
    name: str,
    x: float,
    y: float,
    h: float,
    sx: float,
    sy: float,
    color: str = "0.5 0.5 0.5 1",
    yaw: float = 0.0,
) -> dict[str, Any]:
    return {
        "name": name,
        "kind": "box",
        "x": x,
        "y": y,
        "h": h,
        "sx": sx,
        "sy": sy,
        "yaw": yaw,
        "color": color,
    }


def cyl(
    name: str, x: float, y: float, h: float, r: float, color: str = "0.5 0.5 0.5 1"
) -> dict[str, Any]:
    return {
        "name": name,
        "kind": "cyl",
        "x": x,
        "y": y,
        "h": h,
        "sx": 2 * r,
        "sy": 2 * r,
        "yaw": 0.0,
        "color": color,
    }


def hobby_garden(
    difficulty: int, rng: random.Random
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Raised beds, a gravel path, a pond rim, fence posts and stepping stones; harder = more beds and a narrower path."""
    items = []
    path_half = max(0.45, 0.9 - 0.08 * difficulty)  # the walkable lane along +x
    for i, x in enumerate(range(1, 3 + difficulty)):
        side = 1 if i % 2 == 0 else -1
        items.append(
            box(
                f"bed_{i}",
                x * 0.9 + rng.uniform(-0.1, 0.1),
                side * (path_half + 0.35),
                0.18,
                0.7,
                0.6,
                "0.35 0.22 0.1 1",
            )
        )
    for i in range(4 + difficulty):  # fence posts along the sides
        items.append(cyl(f"post_{i}", 0.6 * i, 1.8, 0.9, 0.03, "0.6 0.45 0.25 1"))
        items.append(cyl(f"post_n{i}", 0.6 * i, -1.8, 0.9, 0.03, "0.6 0.45 0.25 1"))
    items.append(box("pond_rim", 2.0, -path_half - 0.9, 0.05, 1.0, 0.1, "0.2 0.4 0.7 1"))
    for i in range(difficulty):  # stepping stones and roots in the lane: low enough to cross
        items.append(
            cyl(
                f"stone_{i}",
                0.8 + 0.6 * i,
                rng.uniform(-0.2, 0.2),
                0.02 + 0.005 * i,
                0.08,
                "0.55 0.55 0.5 1",
            )
        )
    return items, {
        "ground": "0.25 0.45 0.2 1",
        "mu": 0.55,
    }  # grass: lower friction than the 0.7 floor


def warehouse(difficulty: int, rng: random.Random) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    items = []
    for i in range(2 + difficulty):  # pallets and shelving across the hall, leaving a lane
        x = 0.8 + 0.7 * i
        items.append(box(f"shelf_{i}", x, 1.3, 1.0, 0.4, 0.9, "0.3 0.3 0.6 1"))
        items.append(
            box(f"pallet_{i}", x + rng.uniform(-0.1, 0.1), -1.2, 0.12, 0.8, 0.6, "0.6 0.5 0.3 1")
        )
    items.append(box("cable_cover", 1.5, 0.0, 0.025, 0.1, 1.2, "0.1 0.1 0.1 1"))
    return items, {"ground": "0.5 0.5 0.55 1", "mu": 0.6}


def stair_hall(difficulty: int, rng: random.Random) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    items = []
    for i in range(1, 2 + difficulty):  # low steps across the hall: each at most STEP_LIMIT_M
        items.append(
            box(f"step_{i}", 0.7 * i, 0.0, min(0.015 * i, STEP_LIMIT_M), 0.3, 3.0, "0.7 0.7 0.7 1")
        )
    items.append(box("rail", 1.5, 1.6, 0.9, 3.0, 0.05, "0.2 0.2 0.2 1"))
    return items, {"ground": "0.6 0.6 0.6 1", "mu": 0.7}


BUILDERS = {"hobby_garden": hobby_garden, "warehouse": warehouse, "stair_hall": stair_hall}


def render(name: str, items: list[dict[str, Any]], style: dict[str, Any]) -> str:
    parts = [HEAD.format(name=name, mu=style["mu"], ground=style["ground"])]
    for it in items:
        geom = (
            f"<box><size>{it['sx']:.3f} {it['sy']:.3f} {it['h']:.3f}</size></box>"
            if it["kind"] == "box"
            else f"<cylinder><radius>{it['sx'] / 2:.3f}</radius><length>{it['h']:.3f}</length></cylinder>"
        )
        parts.append(
            f'    <model name="{it["name"]}"><static>true</static><pose>{it["x"]:.3f} {it["y"]:.3f} {it["h"] / 2:.3f} 0 0 {it["yaw"]:.3f}</pose>'
            f'<link name="link"><collision name="c"><geometry>{geom}</geometry></collision>'
            f'<visual name="v"><geometry>{geom}</geometry><material><ambient>{it["color"]}</ambient><diffuse>{it["color"]}</diffuse></material></visual></link></model>\n'
        )
    parts.append("  </world>\n</sdf>\n")
    return "".join(parts)


def _blocked(items: list[dict[str, Any]], x: float, y: float) -> bool:
    for it in items:
        if it["h"] <= STEP_LIMIT_M:
            continue
        rx = it["sx"] / 2 + ROBOT_RADIUS_M
        ry = it["sy"] / 2 + ROBOT_RADIUS_M
        c, s = math.cos(-it["yaw"]), math.sin(-it["yaw"])
        dx, dy = x - it["x"], y - it["y"]
        if abs(dx * c - dy * s) <= rx and abs(dx * s + dy * c) <= ry:
            return True
    return False


def reachable(
    items: list[dict[str, Any]], goal: tuple[float, float] = GOAL, span: float = 2.0
) -> bool:
    """Can a robot of ROBOT_RADIUS_M get from the spawn to the goal, stepping only over low things?"""
    nx, ny = int((goal[0] + 1) / CELL), int(2 * span / CELL)
    start = (int(1 / CELL), ny // 2)
    seen = {start}
    queue = deque([start])
    while queue:
        i, j = queue.popleft()
        if abs((i * CELL - 1) - goal[0]) < 0.1 and abs(j * CELL - span - goal[1]) < 0.1:
            return True
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (i + di, j + dj)
            if n in seen or not (0 <= n[0] <= nx and 0 <= n[1] <= ny):
                continue
            if _blocked(items, n[0] * CELL - 1, n[1] * CELL - span):
                continue
            seen.add(n)
            queue.append(n)
    return False


def check(sdf: str, name: str, items: list[dict[str, Any]] | None = None) -> list[str]:
    """Problems that keep a world out of use (empty list = fine)."""
    problems = []
    try:
        root = ET.fromstring(sdf)  # noqa: S314
    except ET.ParseError as exc:
        return [f"XML geçersiz: {exc}"]
    world = root.find("world")
    if world is None or world.get("name") != name:
        problems.append("dünya adı dosya adıyla aynı değil")
        return problems
    physics = world.find("physics")
    if (
        physics is None
        or physics.get("type") != "dart"
        or float(physics.findtext("max_step_size", "0")) != 0.001
        or float(physics.findtext("real_time_factor", "1")) != 0
    ):
        problems.append("fizik sözleşmesi (DART, 1 ms, gerçek zamansız) bozuk")
    if "gz-physics-dartsim-plugin" not in sdf or "NemlSystem" not in sdf:
        problems.append("zorunlu eklentiler eksik")
    if any(tag.tag == "uri" for tag in root.iter()):
        problems.append("uzak/harici varlık (uri) var: belirlilik bozulur")
    models = world.findall("model")
    if len(models) > 120:
        problems.append(f"çok fazla nesne ({len(models)} > 120)")
    if items is not None:
        for it in items:
            if it["h"] > STEP_LIMIT_M and math.hypot(it["x"], it["y"]) < 0.6:
                problems.append(f"{it['name']} başlangıç bölgesinde")
        if not reachable(items):
            problems.append("hedefe giden yürünebilir yol yok")
    return problems


class WorldStore:
    """Generated worlds on disk plus the index the panel and the sweeps read."""

    def __init__(self, root: Path | None = None) -> None:
        self.dir = root or Path(os.environ.get("NEML_ARTIFACT_DIR", ".")) / "worlds"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._index = self.dir / "index.json"

    def index(self) -> dict[str, dict[str, Any]]:
        try:
            return dict(json.loads(self._index.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return {}

    def names(self) -> list[str]:
        return list(BUILTIN) + sorted(self.index())

    def create(self, template: str, difficulty: int, seed: int = 0) -> dict[str, Any]:
        if template not in BUILDERS:
            raise ValueError(f"şablon: {', '.join(BUILDERS)}")
        difficulty = max(1, min(int(difficulty), 6))
        name = f"{template}_d{difficulty}_s{seed}"
        items, style = BUILDERS[template](
            difficulty, random.Random(f"{template}:{difficulty}:{seed}")
        )  # noqa: S311
        sdf = render(name, items, style)
        problems = check(sdf, name, items)
        if problems:
            return {"name": name, "ok": False, "problems": problems}
        (self.dir / f"{name}.sdf").write_text(sdf, encoding="utf-8")
        index = self.index()
        index[name] = {
            "template": template,
            "difficulty": difficulty,
            "objects": len(items),
            "reachable": True,
        }
        self._index.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        return {"name": name, "ok": True, "objects": len(items)}

    def next_harder(self, passed: str) -> dict[str, Any] | None:
        """A new world one step harder than one the robot has mastered (a new template when the ladder ends)."""
        info = self.index().get(passed)
        template = info["template"] if info else TEMPLATES[len(self.index()) % len(TEMPLATES)]
        level = info["difficulty"] + 1 if info else 1
        if level > 6:
            template, level = TEMPLATES[(TEMPLATES.index(template) + 1) % len(TEMPLATES)], 1
        name = f"{template}_d{level}_s0"
        if name in self.index():
            return None
        return self.create(template, level)
