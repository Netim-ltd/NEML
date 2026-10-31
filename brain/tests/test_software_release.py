# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The software updater never activates an unsigned or unsafe archive."""

from __future__ import annotations

import hashlib
import io
import stat
import zipfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from neml_brain.platform.core import Scope
from neml_brain.platform.software import (
    EdgeSoftwareInstaller,
    SoftwareRelease,
    sign_software_release,
)


def _archive(name: str = "ros2/agent.py") -> bytes:
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(name, "print('ready')\n")
    return memory.getvalue()


def _release(payload: bytes, key: Ed25519PrivateKey) -> SoftwareRelease:
    return sign_software_release(
        SoftwareRelease(
            Scope("firm-a", "home"),
            "robot-1",
            "home-v1",
            "v2",
            hashlib.sha256(payload).hexdigest(),
            "canary",
            "approval-1",
            datetime.now(UTC) + timedelta(hours=1),
        ),
        key,
    )


def _installer(root: Path, key: Ed25519PrivateKey) -> EdgeSoftwareInstaller:
    public = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return EdgeSoftwareInstaller(root, Scope("firm-a", "home"), "robot-1", "home-v1", public)


def test_signed_release_stages_and_rolls_back_on_failed_health(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    installer = _installer(tmp_path, key)
    first = _archive("ros2/first.py")
    release = _release(first, key)
    staged = installer.stage(release, first)
    assert (staged / "payload/ros2/first.py").is_file()
    assert (
        installer.activate(release, robot_stopped=lambda: True, health_check=lambda _: True) == "v2"
    )
    pointer = (tmp_path / "active.json").read_bytes()

    second = _archive("ros2/second.py")
    next_release = sign_software_release(
        replace(_release(second, key), version="v3", signature=""), key
    )
    installer.stage(next_release, second)
    with pytest.raises(RuntimeError, match="health check"):
        installer.activate(next_release, robot_stopped=lambda: True, health_check=lambda _: False)
    assert (tmp_path / "active.json").read_bytes() == pointer


def test_release_requires_identity_signature_approval_and_stopped_robot(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    installer = _installer(tmp_path, key)
    archive = _archive()
    release = _release(archive, key)
    for changed in (
        replace(release, robot_id="robot-2"),
        replace(release, scope=Scope("firm-b", "home")),
        replace(release, approval_id=""),
        replace(release, expires_at=datetime.now(UTC) - timedelta(seconds=1)),
    ):
        with pytest.raises(PermissionError):
            installer.stage(changed, archive)
    with pytest.raises(ValueError, match="digest"):
        installer.stage(release, archive + b"tampered")
    installer.stage(release, archive)
    with pytest.raises(PermissionError, match="stopped"):
        installer.activate(release, robot_stopped=lambda: False, health_check=lambda _: True)
    assert not (tmp_path / "active.json").exists()


@pytest.mark.parametrize("name", ["../escape.py", "/absolute.py", "C:/drive.py"])
def test_archive_rejects_path_escape(tmp_path: Path, name: str) -> None:
    key = Ed25519PrivateKey.generate()
    payload = _archive(name)
    with pytest.raises(ValueError, match="unsafe"):
        _installer(tmp_path, key).stage(_release(payload, key), payload)


def test_archive_rejects_symlinks(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, "w") as bundle:
        link = zipfile.ZipInfo("ros2/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        bundle.writestr(link, "../../outside")
    payload = memory.getvalue()
    with pytest.raises(ValueError, match="link"):
        _installer(tmp_path, key).stage(_release(payload, key), payload)
