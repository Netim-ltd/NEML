# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The MCP servers live next to the brain, not inside it; put both on the path."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

for entry in (REPO_ROOT, REPO_ROOT / "brain"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))
