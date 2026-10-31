# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Immutable tenant-scoped model artifact storage."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from neml_brain.platform.core import Scope


class ModelArtifacts:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _path(self, scope: Scope, robot_type: str, version: str) -> Path:
        # Untrusted identifiers never become path components.
        key = "\x00".join((scope.tenant_id, scope.domain_id, robot_type, version))
        digest = hashlib.sha256(key.encode()).hexdigest()
        return self.root / digest[:2] / f"{digest}.model"

    def put(self, scope: Scope, robot_type: str, version: str, payload: bytes) -> Path:
        if not payload or len(payload) > 100 * 1024 * 1024:
            raise ValueError("model artifact must be 1 byte to 100 MiB")
        target = self._path(scope, robot_type, version)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() == payload:
                return target
            raise FileExistsError("model version already has different bytes")
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            # Hard-link creation is atomic and fails if another writer won.
            os.link(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def get(self, scope: Scope, robot_type: str, version: str, digest: str) -> bytes:
        payload = self._path(scope, robot_type, version).read_bytes()
        if hashlib.sha256(payload).hexdigest() != digest:
            raise ValueError("stored model artifact digest mismatch")
        return payload
