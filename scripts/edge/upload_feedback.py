# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Upload fully attested robot reports to the control plane over HTTPS."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError("feedback upload redirects are forbidden")


def upload(report_dir: Path, endpoint: str) -> int:
    parsed = urlsplit(endpoint)
    if (parsed.scheme != "https" or not parsed.hostname
            or parsed.path != "/v1/platform/feedback" or parsed.query or parsed.fragment):
        raise ValueError("feedback endpoint must be the exact HTTPS API path")
    opener = build_opener(NoRedirect())
    sent = 0
    for path in sorted(report_dir.glob("*.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        if not report.get("robot_signature") or not report.get("verifier_signature"):
            continue
        payload = json.dumps(report, sort_keys=True).encode()
        if len(payload) > 16 * 1024:
            raise ValueError(f"{path.name}: report exceeds 16 KiB")
        request = Request(endpoint, data=payload, method="POST",  # noqa: S310 - HTTPS checked above
                          headers={"Content-Type": "application/json"})
        with opener.open(request, timeout=30) as response:
            if response.status != 201:
                raise ValueError(f"{path.name}: control plane refused report")
        sent += 1
    return sent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", type=Path, required=True)
    parser.add_argument("--endpoint", required=True)
    args = parser.parse_args()
    print(f"{upload(args.reports, args.endpoint)} reports accepted")


if __name__ == "__main__":
    main()
