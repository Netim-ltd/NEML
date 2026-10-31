# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fixed-route advisory mini LLM service for one tenant's operations."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit

import httpx

IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


class OperationModels:
    def __init__(self, routes_json: str, service_key: str) -> None:
        routes = json.loads(routes_json)
        if not isinstance(routes, dict):
            raise ValueError("operation model routes must be a JSON object")
        if routes and len(service_key) < 32:
            raise ValueError("operation model service key must have at least 32 characters")
        checked: dict[tuple[str, str], tuple[str, str]] = {}
        for identity, target in routes.items():
            if not isinstance(identity, str) or identity.count("/") != 1:
                raise ValueError("operation model route must be domain/operation")
            domain, operation = identity.split("/")
            if not IDENTIFIER.fullmatch(domain) or not IDENTIFIER.fullmatch(operation):
                raise ValueError("invalid operation model route identity")
            if not isinstance(target, dict):
                raise ValueError("operation model route must include URL and adapter digest")
            url = target.get("url")
            digest = target.get("adapter_sha256")
            if not isinstance(url, str) or not isinstance(digest, str):
                raise ValueError("operation model URL and digest must be text")
            if not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
                raise ValueError("operation model adapter digest must be SHA-256")
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.path != "/v1/operation/generate"
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("operation model route requires exact HTTPS endpoint")
            checked[(domain, operation)] = (url, digest.lower())
        self.routes = checked
        self.service_key = service_key

    async def generate(
        self, tenant: str, domain: str, operation: str, prompt: str
    ) -> dict[str, Any]:
        if not 1 <= len(prompt) <= 4096:
            raise ValueError("prompt length outside bounds")
        route = self.routes.get((domain, operation))
        if route is None:
            raise KeyError("no active model for this operation")
        url, expected_digest = route
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as http:
            response = await http.post(
                url,
                json={"tenant": tenant, "domain": domain, "operation": operation, "prompt": prompt},
                headers={"Authorization": f"Bearer {self.service_key}"},
            )
            response.raise_for_status()
            if len(response.content) > 16 * 1024:
                raise ValueError("operation model response too large")
            result = response.json()
        if (
            not isinstance(result, dict)
            or result.get("tenant") != tenant
            or result.get("domain") != domain
            or result.get("operation") != operation
            or result.get("adapter_sha256") != expected_digest
            or not isinstance(result.get("completion"), str)
            or len(result["completion"]) > 8192
        ):
            raise ValueError("operation model response identity or content invalid")
        return {
            "completion": result["completion"],
            "use": "advisory_only",
            "adapter_sha256": expected_digest,
        }
