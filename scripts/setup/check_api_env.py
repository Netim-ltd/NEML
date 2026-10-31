# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Validate protected API configuration without printing secret values."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from check_control_env import read_env


def main() -> int:
    api = read_env(Path(sys.argv[1]))
    brain = read_env(Path(sys.argv[2]))
    required = (
        "ConnectionStrings__Default",
        "Jwt__Key",
        "Bridge__ApiKey",
        "NEML_OWNER_EMAIL",
        "NEML_OWNER_PASSWORD",
    )
    errors = [f"{key}: required" for key in required if not api.get(key)]
    for key in required:
        if any(
            marker in api.get(key, "")
            for marker in ("CHANGEME", "example.invalid", "replace-me")
        ):
            errors.append(f"{key}: replace example value")
    connection = api.get("ConnectionStrings__Default", "")
    if not re.search(r"(?:^|;)\s*SSL Mode\s*=\s*VerifyFull(?:;|$)", connection, re.I):
        errors.append("ConnectionStrings__Default: SSL Mode=VerifyFull required")
    for key in ("Jwt__Key", "Bridge__ApiKey"):
        if len(api.get(key, "")) < 32:
            errors.append(f"{key}: at least 32 characters required")
    if len(api.get("NEML_OWNER_PASSWORD", "")) < 12:
        errors.append("NEML_OWNER_PASSWORD: at least 12 characters required")
    if "@" not in api.get("NEML_OWNER_EMAIL", ""):
        errors.append("NEML_OWNER_EMAIL: invalid email")
    if api.get("Bridge__ApiKey") != brain.get("NEML_API_KEY"):
        errors.append("Bridge__ApiKey: must match NEML_API_KEY")
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
