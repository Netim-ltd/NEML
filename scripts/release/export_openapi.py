# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Dump the neml-brain OpenAPI document into docs/api/ (SPEC 15, T-017).

SPEC 15 names `docs/api/` for "OpenAPI çıktıları" and .gitignore keeps the
generated file out of git, so this is what fills the directory:

    python scripts/release/export_openapi.py [docs/api/neml-brain.json]

Importing the app is enough — `create_app()` builds the routers without a
database, a GPU or an MCP daemon, exactly as the SPEC 8.3 contract tests do.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "docs" / "api" / "neml-brain.json"


def export(out: Path = DEFAULT_OUT) -> dict[str, Any]:
    sys.path.insert(0, str(ROOT / "brain"))
    from neml_brain.main import create_app

    schema: dict[str, Any] = create_app().openapi()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return schema


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    out = Path(args[0]) if args else DEFAULT_OUT
    schema = export(out)
    print(f"{out}: {len(schema['paths'])} paths")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
