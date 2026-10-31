# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fail closed before starting the small Compose control plane."""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

REQUIRED = (
    "NEML_DOCKERHUB_NAMESPACE", "NEML_DB_URL", "NEML_VLLM_URL",
    "NEML_EMBED_URL", "NEML_MODEL", "NEML_CLOUD_WS", "NEML_NODE_ID",
    "NEML_API_KEY", "NEML_TENANT_ID", "NEML_TRAINING_EXPORT_KEY",
    "NEML_MODEL_SIGNING_SEED",
    *(f"NEML_MCP_URL_{name}" for name in (
        "FREECAD", "KICAD", "SIM", "FAB", "GENOME", "POSTGRES",
        "FILESYSTEM", "GIT", "BLENDER")),
)


def read_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"line {number}: expected KEY=value")
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) or key in result:
            raise ValueError(f"line {number}: invalid or duplicate key")
        result[key] = value.strip().strip('"').strip("'")
    return result


def validate(env: dict[str, str]) -> list[str]:
    errors = [f"{key}: required" for key in REQUIRED if not env.get(key)]
    for key in REQUIRED:
        value = env.get(key, "")
        if "CHANGEME" in value or "example.invalid" in value or "replace-me" in value:
            errors.append(f"{key}: replace example value")
    namespace = env.get("NEML_DOCKERHUB_NAMESPACE", "")
    if namespace and not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", namespace):
        errors.append("NEML_DOCKERHUB_NAMESPACE: invalid Docker Hub namespace")
    seed = env.get("NEML_MODEL_SIGNING_SEED", "")
    if seed and not re.fullmatch(r"[a-fA-F0-9]{64}", seed):
        errors.append("NEML_MODEL_SIGNING_SEED: expected 32 random bytes as 64 hex characters")
    if env.get("NEML_TRAINING_EXPORT_KEY") and len(env["NEML_TRAINING_EXPORT_KEY"]) < 32:
        errors.append("NEML_TRAINING_EXPORT_KEY: expected at least 32 random characters")
    tenant = env.get("NEML_TENANT_ID", "")
    if tenant and not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", tenant):
        errors.append("NEML_TENANT_ID: invalid tenant ID")
    try:
        routes = json.loads(env.get("NEML_OPERATION_ROUTES", "{}"))
        if not isinstance(routes, dict):
            raise ValueError("expected JSON object")
        if routes:
            for identity, target in routes.items():
                if (not isinstance(identity, str) or identity.count("/") != 1
                        or not all(re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", item)
                                   for item in identity.split("/"))
                        or not isinstance(target, dict)
                        or not isinstance(target.get("url"), str)
                        or not isinstance(target.get("adapter_sha256"), str)
                        or not re.fullmatch(r"[a-fA-F0-9]{64}", target["adapter_sha256"])):
                    errors.append("NEML_OPERATION_ROUTES: invalid route identity or digest")
                    continue
                parsed = urlsplit(target["url"])
                if parsed.scheme != "https" or parsed.path != "/v1/operation/generate":
                    errors.append("NEML_OPERATION_ROUTES: model URL must be exact HTTPS path")
            for key in ("NEML_OPERATION_SERVICE_KEY", "NEML_OPERATION_CLIENT_KEY"):
                if len(env.get(key, "")) < 32 or "CHANGEME" in env.get(key, ""):
                    errors.append(f"{key}: expected at least 32 random characters")
    except ValueError:
        errors.append("NEML_OPERATION_ROUTES: expected JSON object")
    for key in REQUIRED:
        url_keys = ("NEML_DB_URL", "NEML_CLOUD_WS", "NEML_VLLM_URL", "NEML_EMBED_URL")
        if key not in url_keys and not key.startswith("NEML_MCP_URL_"):
            continue
        value = env.get(key, "")
        if not value:
            continue
        parsed = urlsplit(value)
        expected = (
            "postgresql+asyncpg" if key == "NEML_DB_URL"
            else "wss" if key == "NEML_CLOUD_WS" else "https"
        )
        if parsed.scheme != expected or not parsed.hostname:
            errors.append(f"{key}: expected {expected} URL with hostname")
        if key == "NEML_DB_URL" and parse_qs(parsed.query).get("sslmode") != ["verify-full"]:
            errors.append("NEML_DB_URL: require sslmode=verify-full")
        if parsed.hostname in ("localhost", "127.0.0.1", "::1"):
            errors.append(f"{key}: external service cannot use loopback")
    bind = env.get("NEML_BIND_IP", "127.0.0.1")
    try:
        if not ipaddress.ip_address(bind).is_loopback:
            errors.append("NEML_BIND_IP: brain API must bind to loopback")
    except ValueError:
        errors.append("NEML_BIND_IP: expected loopback IP address")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("env_file", type=Path)
    args = parser.parse_args()
    try:
        errors = validate(read_env(args.env_file))
    except (OSError, ValueError) as exc:
        print(f"Invalid environment file: {exc}")
        return 1
    for error in errors:
        print(error)
    if errors:
        return 1
    print("Control-plane environment checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
