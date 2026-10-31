# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Named joint poses of a robot model, kept on the lab (not in one browser).

A pose is a map joint name -> value (radians, metres for prismatic joints). The file per model
sits in the artifact directory; names and numbers are validated because they come from the panel.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

MAX_POSES = 50
MAX_JOINTS = 250
MODEL = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
NAME = re.compile(r"^[^\x00-\x1f]{1,40}$")


class PoseRejected(Exception):
    """The request is not a valid pose operation."""


class PoseStore:
    def __init__(self, directory: Path) -> None:
        self._dir = directory / "poses"

    def _path(self, model: str) -> Path:
        if not MODEL.match(model):
            raise PoseRejected("geçersiz model adı")
        return self._dir / f"{model}.json"

    def list(self, model: str) -> dict[str, dict[str, float]]:
        try:
            data = json.loads(self._path(model).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {str(k): v for k, v in data.items()} if isinstance(data, dict) else {}

    def _write(self, model: str, poses: dict[str, dict[str, float]]) -> None:
        path = self._path(model)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(poses, ensure_ascii=False), encoding="utf-8")

    def save(self, model: str, name: str, values: Any) -> dict[str, dict[str, float]]:
        if not NAME.match(name):
            raise PoseRejected("poz adı 1-40 karakter olmalı")
        if not isinstance(values, dict) or len(values) > MAX_JOINTS:
            raise PoseRejected("poz değerleri bir eklem sözlüğü olmalı")
        clean: dict[str, float] = {}
        for joint, value in values.items():
            if (
                not isinstance(value, int | float)
                or isinstance(value, bool)
                or not math.isfinite(value)
            ):
                raise PoseRejected(f"'{str(joint)[:30]}' için geçerli bir sayı yok")
            clean[str(joint)[:60]] = round(float(value), 6)
        poses = self.list(model)
        if name not in poses and len(poses) >= MAX_POSES:
            raise PoseRejected(f"bir modelde en çok {MAX_POSES} poz saklanır")
        poses[name] = clean
        self._write(model, poses)
        return poses

    def delete(self, model: str, name: str) -> dict[str, dict[str, float]]:
        poses = self.list(model)
        if poses.pop(name, None) is not None:
            self._write(model, poses)
        return poses
