# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pull signed reports from the control API to the isolated GPU worker."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "brain"))
from neml_brain.platform.feedback import verify_report  # noqa: E402


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError("feedback export redirects are forbidden")


def pull(job: dict[str, str], root: Path) -> int:
    base_url = os.environ["NEML_FEEDBACK_EXPORT_URL"]
    token = os.environ["NEML_TRAINING_EXPORT_KEY"]
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.query or parsed.fragment:
        raise ValueError("feedback export requires a fixed HTTPS URL")
    if not parsed.path.endswith("/v1/platform/feedback-export"):
        raise ValueError("feedback export URL must name the exact API route")
    if len(token) < 32:
        raise ValueError("training export key is too short")
    domain_root = (root / "tenants" / job["tenant"] / "domains" / job["domain"]).resolve()
    reports_dir = domain_root / "reports"
    robots: dict[str, str] = {}
    verifiers: dict[str, str] = {}
    fetched: dict[str, dict] = {}
    cursor: str | None = None
    opener = build_opener(NoRedirect())
    for _ in range(1000):
        params = {"tenant": job["tenant"], "domain": job["domain"],
                  "operation": job["operation"]}
        if cursor is not None:
            params["after"] = cursor
        request = Request(  # noqa: S310 - exact HTTPS endpoint checked above
            base_url + "?" + urlencode(params),
            headers={"Authorization": f"Bearer {token}"},
        )
        with opener.open(request, timeout=30) as response:
            if response.status != 200:
                raise ValueError("feedback export failed")
            raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("feedback export response too large")
        page = json.loads(raw)
        rows = page["reports"]
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError("invalid feedback export page")
        for row in rows:
            report = row["report"]
            if (report["tenant_id"] != job["tenant"]
                    or report["domain_id"] != job["domain"]
                    or report["operation"] != job["operation"]):
                raise PermissionError("feedback export crossed tenant/domain/operation")
            report_id = str(UUID(report["report_id"]))
            robot_key = row["robot_public_key"]
            verifier_key = row["verifier_public_key"]
            verify_report(report, bytes.fromhex(robot_key), bytes.fromhex(verifier_key))
            for registry, identity, key in (
                (robots, report["robot_id"], robot_key),
                (verifiers, report["verifier_id"], verifier_key),
            ):
                if identity in registry and registry[identity] != key:
                    raise ValueError("public key changed within export")
                registry[identity] = key
            if report_id in fetched and fetched[report_id] != report:
                raise ValueError("duplicate report ID with different content")
            fetched[report_id] = report
        next_cursor = page.get("next_after")
        if not rows:
            break
        if not next_cursor or next_cursor == cursor:
            raise ValueError("feedback export cursor did not advance")
        cursor = str(UUID(next_cursor))
    else:
        raise ValueError("feedback export exceeded 1000 pages")
    reports_dir.mkdir(parents=True, exist_ok=True)
    for report_id, report in fetched.items():
        destination = reports_dir / f"{report_id}.json"
        if destination.exists():
            existing = json.loads(destination.read_text(encoding="utf-8"))
            if existing != report:
                raise ValueError("local report conflicts with control API")
            continue
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
        os.replace(temporary, destination)
    trust_file = domain_root / "trust.json"
    temporary = trust_file.with_suffix(".tmp")
    temporary.write_text(json.dumps({"robots": robots, "verifiers": verifiers},
                                    sort_keys=True), encoding="utf-8")
    os.replace(temporary, trust_file)
    return len(fetched)
