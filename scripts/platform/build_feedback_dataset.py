# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Turn independently verified robot recovery reports into a LoRA JSONL set."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "brain"))
from neml_brain.platform.feedback import training_pair, verify_report  # noqa: E402


def build(job: dict[str, str], root: Path) -> int:
    domain_root = (root / "tenants" / job["tenant"] / "domains" / job["domain"]).resolve()
    reports = (domain_root / "reports").resolve()
    trust_file = (domain_root / "trust.json").resolve()
    if not reports.is_dir() or not trust_file.is_file():
        raise FileNotFoundError("robot reports or trusted public-key registry missing")
    trust = json.loads(trust_file.read_text(encoding="utf-8"))
    robots = trust["robots"]
    verifiers = trust["verifiers"]
    pairs: dict[str, dict] = {}
    seen_ids: set[str] = set()
    for path in sorted(reports.glob("*.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        if (report.get("tenant_id") != job["tenant"]
                or report.get("domain_id") != job["domain"]
                or report.get("operation") != job["operation"]):
            continue
        report_id = report["report_id"]
        if report_id in seen_ids:
            raise ValueError("duplicate robot report ID")
        seen_ids.add(report_id)
        robot_key = bytes.fromhex(robots[report["robot_id"]])
        verifier_key = bytes.fromhex(verifiers[report["verifier_id"]])
        if robot_key == verifier_key:
            raise ValueError("robot and outcome verifier must use separate keys")
        verify_report(report, robot_key, verifier_key)
        pair = training_pair(report)
        pairs[pair["source_sha256"]] = pair
    dataset = Path(job["dataset"])
    if not dataset.is_relative_to(domain_root):
        raise ValueError("dataset escapes tenant/domain directory")
    dataset.parent.mkdir(parents=True, exist_ok=True)
    tmp = dataset.with_suffix(dataset.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as stream:
        for pair in pairs.values():
            stream.write(json.dumps(pair, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, dataset)
    return len(pairs)
