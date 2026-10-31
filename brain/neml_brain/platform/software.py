# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Signed, robot-scoped software staging with atomic activation and rollback.

This prepares ROS 2 application bundles. It never flashes firmware or bypasses
the independent motor safety controller. A robot supervisor supplies the stop
and health checks before activating a staged release.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import tempfile
import threading
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from neml_brain.platform.core import Scope

MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_UNPACKED_BYTES = 200 * 1024 * 1024
MAX_FILES = 512


@dataclass(frozen=True)
class SoftwareRelease:
    scope: Scope
    robot_id: str
    robot_type: str
    version: str
    archive_sha256: str
    stage: str
    approval_id: str
    expires_at: datetime
    signature: str = ""

    def signed_bytes(self) -> bytes:
        return json.dumps(
            {
                "tenant_id": self.scope.tenant_id,
                "domain_id": self.scope.domain_id,
                "robot_id": self.robot_id,
                "robot_type": self.robot_type,
                "version": self.version,
                "archive_sha256": self.archive_sha256,
                "stage": self.stage,
                "approval_id": self.approval_id,
                "expires_at": self.expires_at.isoformat(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()


def sign_software_release(release: SoftwareRelease, key: Ed25519PrivateKey) -> SoftwareRelease:
    """Called by a control-plane release manager after human approval."""
    if not release.approval_id or release.stage not in {"canary", "fleet", "rollback"}:
        raise PermissionError("software release needs an approved rollout stage")
    return replace(release, signature=key.sign(release.signed_bytes()).hex())


class EdgeSoftwareInstaller:
    """Single-agent release store; the supervisor controls when activation runs."""

    def __init__(
        self,
        root: Path,
        scope: Scope,
        robot_id: str,
        robot_type: str,
        lab_public_key: bytes,
    ) -> None:
        self.root = root.resolve()
        self.scope = scope
        self.robot_id = robot_id
        self.robot_type = robot_type
        self.key = Ed25519PublicKey.from_public_bytes(lab_public_key)
        self._lock = threading.Lock()

    def _verify(self, release: SoftwareRelease) -> None:
        if release.scope != self.scope or release.robot_id != self.robot_id:
            raise PermissionError("software release targets another robot or tenant")
        if release.robot_type != self.robot_type:
            raise PermissionError("software release targets another robot type")
        if release.stage not in {"canary", "fleet", "rollback"} or not release.approval_id:
            raise PermissionError("software rollout needs a human approval")
        if release.expires_at.tzinfo is None or release.expires_at <= datetime.now(UTC):
            raise PermissionError("software release expired")
        if len(release.archive_sha256) != 64:
            raise ValueError("invalid archive digest")
        try:
            self.key.verify(bytes.fromhex(release.signature), release.signed_bytes())
        except (InvalidSignature, ValueError) as exc:
            raise PermissionError("software release signature invalid") from exc

    @staticmethod
    def _members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
        members = archive.infolist()
        if not members or len(members) > MAX_FILES:
            raise ValueError("software archive has an invalid file count")
        total = 0
        seen: set[str] = set()
        for member in members:
            path = PurePosixPath(member.filename)
            if (
                member.filename.startswith("/")
                or "\\" in member.filename
                or not path.parts
                or any(part in {"", ".", ".."} for part in path.parts)
                or ":" in path.parts[0]
                or member.filename in seen
                or member.flag_bits & 1
            ):
                raise ValueError("unsafe software archive path")
            seen.add(member.filename)
            mode = stat.S_IFMT(member.external_attr >> 16)
            if mode not in {0, stat.S_IFREG, stat.S_IFDIR}:
                raise ValueError("software archive contains a link or device")
            if not member.is_dir():
                total += member.file_size
                if member.file_size > MAX_ARCHIVE_BYTES or total > MAX_UNPACKED_BYTES:
                    raise ValueError("software archive expands beyond the size limit")
        return members

    def stage(self, release: SoftwareRelease, archive_bytes: bytes) -> Path:
        self._verify(release)
        if not archive_bytes or len(archive_bytes) > MAX_ARCHIVE_BYTES:
            raise ValueError("software archive size is invalid")
        digest = hashlib.sha256(archive_bytes).hexdigest()
        if digest != release.archive_sha256:
            raise ValueError("software archive digest mismatch")
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            members = self._members(archive)
            self.root.mkdir(parents=True, exist_ok=True)
            target = self.root / digest
            with self._lock:
                if target.exists():
                    if hashlib.sha256((target / "archive.zip").read_bytes()).hexdigest() != digest:
                        raise ValueError("existing staged release is corrupt")
                    return target
                with tempfile.TemporaryDirectory(dir=self.root, prefix=".staging-") as temporary:
                    staging = Path(temporary)
                    payload = staging / "payload"
                    payload.mkdir()
                    for member in members:
                        destination = payload.joinpath(*PurePosixPath(member.filename).parts)
                        if member.is_dir():
                            destination.mkdir(parents=True, exist_ok=True)
                            continue
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(member) as source, destination.open("xb") as output:
                            copied = 0
                            while chunk := source.read(1024 * 1024):
                                copied += len(chunk)
                                if copied > member.file_size:
                                    raise ValueError(
                                        "software archive entry exceeded declared size"
                                    )
                                output.write(chunk)
                            output.flush()
                            os.fsync(output.fileno())
                    (staging / "archive.zip").write_bytes(archive_bytes)
                    os.replace(staging, target)
            return target

    def _pointer(self, value: dict[str, str]) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=self.root, delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(self.root / "active.json")

    def activate(
        self,
        release: SoftwareRelease,
        *,
        robot_stopped: Callable[[], bool],
        health_check: Callable[[Path], bool],
    ) -> str:
        """Switch only while stopped; restore the old pointer if health fails."""
        self._verify(release)
        with self._lock:
            target = self.root / release.archive_sha256
            archive = target / "archive.zip"
            if (
                not archive.is_file()
                or hashlib.sha256(archive.read_bytes()).hexdigest() != release.archive_sha256
            ):
                raise ValueError("software release is not staged or has changed")
            if not robot_stopped():
                raise PermissionError("robot must be stopped before software activation")
            pointer = self.root / "active.json"
            previous = json.loads(pointer.read_text(encoding="utf-8")) if pointer.exists() else None
            self._pointer({"version": release.version, "sha256": release.archive_sha256})
            try:
                if not health_check(target / "payload"):
                    raise RuntimeError("software health check failed")
            except BaseException:
                if previous is None:
                    pointer.unlink(missing_ok=True)
                else:
                    self._pointer(previous)
                raise
            return release.version
