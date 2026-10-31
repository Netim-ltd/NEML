# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run tenant/task LoRA jobs during the Istanbul night window on a GPU host."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
REQUIRED = {"tenant", "domain", "operation", "base_model", "base_revision", "dataset", "output"}
TZ = ZoneInfo("Europe/Istanbul")


def night_window(now: datetime) -> bool:
    clock = now.astimezone(TZ).time()
    return clock >= time(23, 59) or clock < time(4, 59)


def load_job(path: Path, root: Path) -> dict[str, str]:
    job = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(job, dict) or not REQUIRED <= job.keys():
        raise ValueError(f"{path.name}: missing job fields")
    for key in ("tenant", "domain", "operation"):
        if not isinstance(job[key], str) or not IDENTIFIER.fullmatch(job[key]):
            raise ValueError(f"{path.name}: invalid {key}")
    for key in ("dataset", "output"):
        value = job[key]
        if not isinstance(value, str):
            raise ValueError(f"{path.name}: invalid {key}")
        target = (root / value).resolve()
        if not target.is_relative_to(root.resolve()) or target == root.resolve():
            raise ValueError(f"{path.name}: {key} escapes training root")
        domain_root = (root / "tenants" / job["tenant"] / "domains" / job["domain"]).resolve()
        if not target.is_relative_to(domain_root):
            raise ValueError(f"{path.name}: {key} must stay in its tenant/domain directory")
        job[key] = str(target)
    if (Path(job["dataset"]).is_relative_to(Path(job["output"]))
            or Path(job["output"]).is_relative_to(Path(job["dataset"]))):
        raise ValueError(f"{path.name}: dataset and output overlap")
    for key in ("base_model", "base_revision"):
        if not isinstance(job[key], str) or not job[key] or any(c.isspace() for c in job[key]):
            raise ValueError(f"{path.name}: invalid {key}")
    if not re.fullmatch(r"[a-fA-F0-9]{40}", job["base_revision"]):
        raise ValueError(f"{path.name}: base_revision must pin a 40-character commit")
    if job.get("source", "curated") not in ("curated", "robot_feedback"):
        raise ValueError(f"{path.name}: unknown source")
    if job.get("transport", "local") not in ("local", "control_api"):
        raise ValueError(f"{path.name}: unknown feedback transport")
    if job.get("transport") == "control_api" and job.get("source") != "robot_feedback":
        raise ValueError(f"{path.name}: control API transport needs robot_feedback source")
    if job.get("quantization", "none") not in ("none", "nf4"):
        raise ValueError(f"{path.name}: unsupported quantization")
    return job


def dataset_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(root: Path, *, now: datetime, dry_run: bool = False) -> int:
    if not night_window(now):
        raise PermissionError("LoRA training is allowed only 23:59–04:59 Europe/Istanbul")
    jobs_dir = root / "jobs"
    if not jobs_dir.is_dir():
        raise FileNotFoundError("training jobs directory is missing")
    failures = 0
    for path in sorted(jobs_dir.glob("*.json")):
        try:
            job = load_job(path, root)
            if job.get("source") == "robot_feedback" and not dry_run:
                if job.get("transport") == "control_api":
                    from pull_feedback import pull

                    fetched = pull(job, root)
                    print(f"{job['tenant']}/{job['domain']}/{job['operation']}: "
                          f"{fetched} reports pulled")
                from build_feedback_dataset import build

                count = build(job, root)
                print(f"{job['tenant']}/{job['operation']}: {count} verified recovery reports")
            data = Path(job["dataset"])
            if not data.is_file():
                raise FileNotFoundError("dataset is missing")
            digest = dataset_digest(data)
            output = Path(job["output"])
            marker = output / "last-success.json"
            if marker.exists():
                previous = json.loads(marker.read_text(encoding="utf-8"))
                if (previous.get("dataset_sha256") == digest
                        and previous.get("base_revision") == job["base_revision"]):
                    print(f"{job['tenant']}/{job['operation']}: unchanged dataset; skipped")
                    continue
            print(f"{job['tenant']}/{job['operation']}: {'would train' if dry_run else 'training'}")
            if dry_run:
                continue
            output.mkdir(parents=True, exist_ok=True)
            subprocess.run(  # noqa: S603 - fixed interpreter/script, argument list, no shell
                [sys.executable, str(Path(__file__).with_name("lora_worker.py")),
                 "--job", str(path), "--root", str(root)],
                check=True,
                timeout=4 * 60 * 60,
                env={**os.environ, "NEML_DATASET_SHA256": digest},
            )
        except (KeyError, ValueError, OSError, subprocess.SubprocessError) as exc:
            failures += 1
            print(f"{path.name}: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return run(args.root.resolve(), now=datetime.now(TZ), dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
