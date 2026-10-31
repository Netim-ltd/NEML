<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# Robot software release boundary

`brain/neml_brain/platform/software.py` stages signed ROS 2 application ZIPs
for one tenant, domain, robot and robot type. It checks the release signature,
approval reference, expiry and archive digest before unpacking. The unpacker
rejects path traversal, links, device entries, encrypted ZIPs and oversized
packages. A release is stored under its content digest; activation swaps only
an `active.json` pointer. If the supervisor's health check fails, the previous
pointer is restored. The previous package remains on disk.

The control plane must sign a `SoftwareRelease` only after checking a real
human approval for the exact version, target robot and rollout stage. The
robot supervisor must call `activate` only after confirming the robot is
stopped, and its health callback must verify the new ROS 2 processes before
motion is re-enabled. A generic `lambda: True` is suitable only for unit
tests. Firmware flashing and motor-controller updates are outside this module.

The repository does not yet provide the software release API, approval ledger
transition, robot polling agent, ROS 2 supervisor integration or firmware
flasher. Thus the module is a tested package and rollback primitive, not a
claim that physical OTA is ready. These integrations need a specific robot
software layout and bench validation before activation on a real fleet.
