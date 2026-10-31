# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Write the two protected env files (NEML_API_ENV, NEML_BRAIN_ENV) for GitHub.

Random values are generated here; values only you can know (database host,
GPU URL, your e-mail) come in as flags. Anything left out stays a `replace-me`
marker, which scripts/setup/check_*_env.py rejects, so a half-filled file can
never deploy. Files are written to --out (outside the repo) with mode 0600 and
no secret is printed.

    python scripts/setup/generate_secrets.py --out ~/neml-secrets \
        --owner-email you@example.com --namespace dockerhubuser --tenant netim \
        --db-host db.example.com --api-db-password '...' --brain-db-password '...' \
        --llm-url https://gpu.example.com/v1 --embed-url https://embed.example.com \
        --mcp-base https://lab.example.com
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_control_env import read_env, validate  # noqa: E402

MARK = "replace-me"
MCP = ("freecad", "kicad", "sim", "fab", "genome", "postgres", "filesystem", "git", "blender")


def api_env(a: argparse.Namespace, bridge_key: str) -> str:
    db = (
        f"Host={a.db_host or MARK};Port=5432;Database=neml_cloud;Username=neml;"
        f"Password={a.api_db_password or MARK};SSL Mode=VerifyFull"
    )
    return "\n".join(
        [
            "ASPNETCORE_ENVIRONMENT=Production",
            f"ConnectionStrings__Default={db}",
            f"Jwt__Key={secrets.token_urlsafe(48)}",
            f"Bridge__ApiKey={bridge_key}",
            f"Bridge__NodeIds__0={a.node_id}",
            f"NEML_OWNER_EMAIL={a.owner_email or MARK}",
            f"NEML_OWNER_PASSWORD={a.owner_password or secrets.token_urlsafe(18)}",
            "",
        ]
    )


def brain_env(a: argparse.Namespace, bridge_key: str) -> str:
    db = (
        f"postgresql+asyncpg://neml:{a.brain_db_password or MARK}@{a.db_host or MARK}:5432/neml"
        "?sslmode=verify-full"
    )
    base = (a.mcp_base or f"https://{MARK}").rstrip("/")
    lines = [
        f"NEML_DOCKERHUB_NAMESPACE={a.namespace or MARK}",
        "NEML_IMAGE_TAG=1.0",
        "NEML_BIND_IP=127.0.0.1",
        "NEML_ENV=lab",
        f"NEML_DB_URL={db}",
        f"NEML_VLLM_URL={a.llm_url or f'https://{MARK}/v1'}",
        f"NEML_EMBED_URL={a.embed_url or f'https://{MARK}'}",
        "NEML_MODEL=Qwen/Qwen2.5-Coder-1.5B-Instruct-AWQ",
        "NEML_CLOUD_WS=wss://api.neml.easyway-sharing.com/bridge/ws",
        f"NEML_NODE_ID={a.node_id}",
        f"NEML_API_KEY={bridge_key}",
        f"NEML_OWNERS={a.owner_email or ''}",  # decided_by is the owner's login e-mail
        f"NEML_TENANT_ID={a.tenant or MARK}",
        f"NEML_TRAINING_EXPORT_KEY={secrets.token_urlsafe(48)}",
        "NEML_OPERATION_ROUTES={}",
        f"NEML_MODEL_SIGNING_SEED={secrets.token_hex(32)}",
        *(f"NEML_MCP_URL_{name.upper()}={base}/{name}/mcp" for name in MCP),
        "",
    ]
    return "\n".join(lines)


def write_private(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    os.chmod(path, 0o600)  # no-op on Windows; the folder ACL is the protection there


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--out", type=Path, required=True)
    for flag in (
        "owner-email owner-password namespace tenant db-host api-db-password "
        "brain-db-password llm-url embed-url mcp-base"
    ).split():
        p.add_argument(f"--{flag}")
    p.add_argument("--node-id", default="neml-control-01")
    a = p.parse_args(argv)
    if a.owner_email and "@" not in a.owner_email:
        p.error("--owner-email must be an e-mail address")
    a.out.mkdir(parents=True, exist_ok=True)
    bridge_key = secrets.token_urlsafe(48)
    api_path, brain_path = a.out / "NEML_API_ENV.txt", a.out / "NEML_BRAIN_ENV.txt"
    write_private(api_path, api_env(a, bridge_key))
    write_private(brain_path, brain_env(a, bridge_key))
    missing = validate(read_env(brain_path))
    missing += [f"{k}: replace-me" for k, v in read_env(api_path).items() if MARK in v]
    print(f"written: {api_path}\nwritten: {brain_path}")
    print("still to fill:" if missing else "all values present; run the check scripts.")
    for line in missing:
        print("  -", line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
