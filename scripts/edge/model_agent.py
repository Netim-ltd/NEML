# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Raspberry Pi model updater. Runs separately from the hardware safety MCU."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from neml_brain.platform.core import Scope
from neml_brain.platform.edge import EdgeRuntime
from neml_brain.platform.robots import FieldRobot, HomeRobot, PluginRegistry


async def main() -> None:
    scope = Scope(os.environ["NEML_TENANT_ID"], os.environ["NEML_DOMAIN_ID"])
    robot_id = os.environ["NEML_ROBOT_ID"]
    robot_type = os.environ["NEML_ROBOT_TYPE"]
    base_url = os.environ["NEML_LAB_HTTPS_URL"].rstrip("/")
    if not base_url.startswith("https://"):
        raise ValueError("lab endpoint must be HTTPS")
    registry = PluginRegistry()
    registry.register(HomeRobot())
    registry.register(FieldRobot())
    registry.load_installed()
    plugin = next(
        (item for item in registry.capable(frozenset()) if item.type_id == robot_type), None
    )
    if plugin is None:
        raise ValueError("robot type plugin is not installed")
    device_key = Ed25519PrivateKey.from_private_bytes(
        bytes.fromhex(Path(os.environ["NEML_DEVICE_PRIVATE_KEY_FILE"]).read_text().strip())
    )
    lab_public = bytes.fromhex(Path(os.environ["NEML_LAB_PUBLIC_KEY_FILE"]).read_text().strip())
    edge = EdgeRuntime(
        scope,
        robot_id,
        robot_type,
        lab_public,
        Path(os.environ["NEML_EDGE_MODEL_DIR"]),
        plugin.envelope,
    )
    while True:
        try:
            await edge.poll_and_deploy(
                f"{base_url}/v1/platform/ticket-request",
                f"{base_url}/v1/platform/model-bundle",
                f"{base_url}/v1/platform/model-ack",
                device_key,
            )
        except Exception as exc:  # noqa: BLE001 - keep current signed model active
            print(f"model update failed: {type(exc).__name__}: {exc}", flush=True)
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
