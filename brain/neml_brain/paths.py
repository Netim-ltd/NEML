# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where config/ and hardware/ live.

From a source checkout the repo root is two levels above this package. Once the
package is pip-installed (the container image) that is site-packages, so the image
sets NEML_ROOT=/app and NEML_CONFIG_DIR=/app/config instead.
"""

import os
from pathlib import Path

REPO_ROOT = Path(os.environ.get("NEML_ROOT") or Path(__file__).resolve().parents[2])
CONFIG_DIR = Path(os.environ.get("NEML_CONFIG_DIR") or REPO_ROOT / "config")
