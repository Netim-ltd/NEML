# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Robot-side hook: sign a completed failure/recovery trace for outcome verification."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from neml_brain.platform.feedback import sign_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path, help="JSON from robot telemetry callback")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    trace = json.loads(args.trace.read_text(encoding="utf-8"))
    report = {
        "tenant_id": os.environ["NEML_TENANT_ID"],
        "domain_id": os.environ["NEML_DOMAIN_ID"],
        "robot_id": os.environ["NEML_ROBOT_ID"],
        "robot_type": os.environ["NEML_ROBOT_TYPE"],
        "operation": trace["operation"],
        "report_id": str(uuid4()),
        "occurred_at": datetime.now(UTC).isoformat(),
        "features": trace["features"],
        "failed_action": trace["failed_action"],
        "failure_class": trace["failure_class"],
        "recovery_action": trace["recovery_action"],
        "outcome": trace["outcome"],
        "quality": trace["quality"],
        "verifier_id": trace["verifier_id"],
    }
    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(
        Path(os.environ["NEML_DEVICE_PRIVATE_KEY_FILE"]).read_text(encoding="utf-8").strip()
    ))
    report["robot_signature"] = sign_report(report, key)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    destination = args.output_dir / f"{report['report_id']}.json"
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
    os.replace(temporary, destination)
    print(destination)


if __name__ == "__main__":
    main()
