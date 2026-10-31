# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Print job records and the SPEC 9.4 PrintProgress payload (SPEC 12.4, T-095).

A dropped printer connection must not lose the job. `start` writes a JSON record
under manufacturing/jobs/ before the first poll; reconnecting reads that record
back instead of opening a second one for the same printer job id.

The record is also what turns a PrusaLink reply into the SPEC 9.4 payload:
`GET /api/v1/status` carries neither the layer number nor the layer count, so
`layer` is derived from the progress percentage and the layer count the slicer
reported at upload time.
"""

from __future__ import annotations

import dataclasses
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# SPEC 9.4 throttles TelemetryTick to 1 Hz; a print moves far slower than that.
POLL_INTERVAL_S = 5.0

# PrusaLink printer states that mean "still ours". Everything else (FINISHED,
# STOPPED, ERROR, IDLE, READY, ...) ends tracking.
ACTIVE_STATES = frozenset({"PRINTING", "PAUSED", "BUSY", "ATTENTION"})

_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


class JobRecordError(RuntimeError):
    """An id from the printer is not safe to use as a file name."""


@dataclass
class JobRecord:
    """One print, as the lab knows it. Survives a brain restart."""

    job_id: str
    printer_id: str
    remote_path: str
    approval_token: str
    filament_g: float = 0.0
    layer_count: int = 0
    state: str = "queued"
    pct: float = 0.0
    nozzle_c: float = 0.0
    bed_c: float = 0.0
    remaining_s: int = 0
    adopted: bool = False  # found on the printer, not started by this process
    updated_at: str = ""


def _safe(value: str, what: str) -> str:
    """Printer-supplied ids become file names, so they are checked, not trusted."""
    if not _ID_RE.fullmatch(value):
        raise JobRecordError(f"illegal {what} {value!r}")
    return value


def path(jobs_dir: Path, printer_id: str, job_id: str) -> Path:
    return jobs_dir / f"{_safe(printer_id, 'printer id')}__{_safe(job_id, 'job id')}.json"


def save(jobs_dir: Path, record: JobRecord) -> Path:
    record.updated_at = datetime.now(UTC).isoformat()
    file = path(jobs_dir, record.printer_id, record.job_id)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(dataclasses.asdict(record), indent=2), encoding="utf-8")
    return file


def load(jobs_dir: Path, printer_id: str, job_id: str) -> JobRecord | None:
    file = path(jobs_dir, printer_id, job_id)
    if not file.is_file():
        return None
    return JobRecord(**json.loads(file.read_text(encoding="utf-8")))


def is_active(record: JobRecord) -> bool:
    """Is this print still running?

    Case-folded on purpose: start() writes the SPEC 7 print_jobs vocabulary
    ('printing') and reconcile() overwrites it with whatever PrusaLink shouts
    ('PRINTING'). Matching only one of the two silently ends tracking.
    """
    return record.state.upper() in ACTIVE_STATES


def progress(record: JobRecord) -> dict[str, Any]:
    """The SPEC 9.4 PrintProgress payload, field for field."""
    return {
        "jobId": record.job_id,
        "pct": round(record.pct, 1),
        "layer": round(record.layer_count * record.pct / 100.0),
        "etaMin": round(record.remaining_s / 60.0),
        "nozzleC": record.nozzle_c,
        "bedC": record.bed_c,
    }
