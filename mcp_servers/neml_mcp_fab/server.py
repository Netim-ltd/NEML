# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""neml-mcp-fab - PrusaSlicer + G-code Viewer + PrusaLink, port 9102 (SPEC 6.4).

SPEC 1.3: PrusaSlicer and Prusa G-code Viewer are AGPL-3.0. They are invoked as
separate processes only. No PrusaSlicer code is copied, linked or embedded in
this tree, and this daemon never exposes them as a network service.

SPEC 5.2 level 4 (MANUFACTURE): `start` refuses to run without an approval token.
SPEC 14.4: it also refuses when the print would blow the daily 500 g filament budget.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import sqlalchemy as sa

from mcp_servers._common import CliTimeout, make_app, run_cli
from mcp_servers.neml_mcp_fab import gcode, jobs, qc
from mcp_servers.neml_mcp_genome import server as genome_server

PORT = 9102
VERSION = "1.0.0"
DEFAULT_TIMEOUT_S = 120.0
REPO_ROOT = Path(__file__).resolve().parents[2]
FILAMENT_BUDGET = "filament_grams"  # SPEC 14.4, config/budget.yaml

_SELECT_PROFILE = sa.text("SELECT profile_id FROM print_jobs WHERE id = CAST(:id AS uuid)")
_UPDATE_QC = sa.text("UPDATE print_jobs SET qc = CAST(:qc AS jsonb) WHERE id = CAST(:id AS uuid)")

# Fallback price, used only for G-code with no `; filament cost =` line. The real
# figure comes from the slicer, which reads filament_cost out of the profile.
# ponytail: one number for four materials. Ceiling is a wrong quote on hand-written
# G-code; the upgrade path is reading filament_cost out of the profile directly.
FILAMENT_TRY_PER_G = 0.6  # owner price: 600 TRY per kg


class FabError(RuntimeError):
    """Base typed error for every fab entry point."""


class FabTimeoutError(FabError):
    """Slicer, viewer or printer did not answer inside the timeout."""


class ApprovalRequiredError(FabError):
    """SPEC 5.2 level 4: MANUFACTURE needs a human approval token."""


class BudgetExhaustedError(FabError):
    """SPEC 14.4: the daily 500 g filament budget would not cover this print."""


@dataclass
class GcodeResult:
    gcode_path: str
    model_3mf: str
    profile_id: str
    sha256: str


@dataclass
class GcodeReport:
    gcode_path: str
    preview_png: str
    time_h: float
    filament_g: float
    filament_mm: float
    layer_count: int
    max_temp_c: float
    retractions: int
    max_bridge_mm: float
    support_volume_mm3: float
    max_bed_temp_c: float = 0.0  # M140/M190, ADR-014


@dataclass
class FileHandle:
    printer_id: str
    name: str
    remote_path: str
    size_bytes: int
    # Read off the uploaded G-code: `start` charges the SPEC 14.4 filament budget
    # with it, and the job record needs the layer count for SPEC 9.4 PrintProgress.
    filament_g: float = 0.0
    time_h: float = 0.0
    layer_count: int = 0


@dataclass
class JobHandle:
    printer_id: str
    job_id: str
    remote_path: str
    approval_token: str


@dataclass
class PrinterStatus:
    printer_id: str
    state: str
    progress_pct: float
    job_id: str | None
    nozzle_c: float
    bed_c: float
    remaining_s: int


Runner = Callable[[list[str], float], Awaitable[str]]


@dataclass
class _State:
    runner: Runner = run_cli
    http: httpx.AsyncClient | None = None
    work_dir: Path = field(
        default_factory=lambda: Path(os.getenv("NEML_WORK_DIR", "/srv/neml/work")) / "fab"
    )
    profile_dir: Path = field(
        default_factory=lambda: REPO_ROOT / "manufacturing" / "slicer_profiles"
    )
    jobs_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("NEML_JOBS_DIR", REPO_ROOT / "manufacturing" / "jobs")
        )
    )
    budget: Any = None  # neml_brain.runtime.budget.Budget, lazily
    session_factory: Any = None  # neml_brain.db.session.get_sessionmaker(), lazily


_S = _State()


def configure(
    runner: Runner | None = None,
    http: httpx.AsyncClient | None = None,
    work_dir: Path | None = None,
    profile_dir: Path | None = None,
    jobs_dir: Path | None = None,
    budget: Any = None,
    session_factory: Any = None,
) -> None:
    if runner is not None:
        _S.runner = runner
    if http is not None:
        _S.http = http
    if work_dir is not None:
        _S.work_dir = Path(work_dir)
    if profile_dir is not None:
        _S.profile_dir = Path(profile_dir)
    if jobs_dir is not None:
        _S.jobs_dir = Path(jobs_dir)
    if budget is not None:
        _S.budget = budget
    if session_factory is not None:
        _S.session_factory = session_factory


def _http() -> httpx.AsyncClient:
    if _S.http is None:
        _S.http = httpx.AsyncClient()
    return _S.http


def _budget() -> Any:
    if _S.budget is None:
        # Imported lazily: the budget lives in the brain package (SPEC 14.4) and
        # this daemon must still import cleanly when it is not installed.
        # ponytail: the counter is per process, so this daemon and the brain each
        # hold one. Ceiling is a double-spend across processes; upgrade path is the
        # budget table brain/neml_brain/runtime/budget.py already names.
        from neml_brain.runtime.budget import Budget

        _S.budget = Budget()
    return _S.budget


def _sessions() -> Any:
    if _S.session_factory is None:
        from neml_brain.db.session import get_sessionmaker

        _S.session_factory = get_sessionmaker()
    return _S.session_factory


def _printer(printer_id: str) -> tuple[str, str]:
    """ponytail: one printer in the lab, so PrusaLink creds come from .env.
    Add a printers table when a second printer arrives."""
    base = os.getenv("PRUSALINK_URL")
    key = os.getenv("PRUSALINK_API_KEY")
    if not base or not key:
        raise FabError(f"PRUSALINK_URL / PRUSALINK_API_KEY not set for printer '{printer_id}'")
    return base.rstrip("/"), key


async def _cli(argv: list[str], timeout_s: float) -> str:
    try:
        return await _S.runner(argv, timeout_s)
    except CliTimeout as exc:
        raise FabTimeoutError(str(exc)) from exc
    except FabError:
        raise
    except Exception as exc:
        raise FabError(f"{argv[0]} failed: {type(exc).__name__}: {exc}") from exc


async def _request(method: str, url: str, timeout_s: float, **kwargs: Any) -> httpx.Response:
    try:
        response = await _http().request(method, url, timeout=timeout_s, **kwargs)
        response.raise_for_status()
        return response
    except httpx.TimeoutException as exc:
        raise FabTimeoutError(f"{method} {url} timed out after {timeout_s}s") from exc
    except httpx.HTTPError as exc:
        raise FabError(f"{method} {url} failed: {exc}") from exc


def _read_gcode(gcode_path: str) -> str:
    file = Path(gcode_path)
    if not file.is_file():
        raise FabError(f"gcode not found: {gcode_path}")
    return file.read_text(encoding="utf-8", errors="replace")


# --- SPEC 6.4 interface contract -------------------------------------------


async def slice(  # noqa: A001 - the spec names this tool `slice`
    model_3mf: str, profile_id: str, timeout_s: float = DEFAULT_TIMEOUT_S
) -> GcodeResult:
    """Slice a 3MF with a named slicer profile."""
    model = Path(model_3mf)
    if not model.is_file():
        raise FabError(f"model not found: {model_3mf}")
    profile = _S.profile_dir / f"{profile_id}.ini"
    if not profile.is_file():
        raise FabError(f"slicer profile not found: {profile}")
    _S.work_dir.mkdir(parents=True, exist_ok=True)
    out = _S.work_dir / f"{model.stem}__{profile_id}.gcode"
    # SPEC 1.3: AGPL-3.0 tool, called as a subprocess. Never linked, never embedded.
    await _cli(
        [
            os.getenv("PRUSASLICER_BIN", "prusa-slicer"),
            "--export-gcode",
            "--load",
            str(profile),
            "--output",
            str(out),
            str(model),
        ],
        timeout_s,
    )
    if not out.is_file():
        raise FabError(f"slicer produced no gcode at {out}")
    return GcodeResult(
        gcode_path=str(out),
        model_3mf=str(model),
        profile_id=profile_id,
        sha256=hashlib.sha256(out.read_bytes()).hexdigest(),
    )


async def validate_gcode(gcode_path: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> GcodeReport:
    """Parse the print and render the PNG the approval screen shows (SPEC 12.4)."""
    text = _read_gcode(gcode_path)
    png = Path(gcode_path).with_suffix(".png")
    # SPEC 1.3: AGPL-3.0 tool, called as a subprocess. Never linked, never embedded.
    await _cli(
        [
            os.getenv("PRUSA_GCODEVIEWER_BIN", "prusa-gcodeviewer"),
            "--export-png",
            str(png),
            str(gcode_path),
        ],
        timeout_s,
    )
    if not png.is_file():
        # The approval screen is the PNG (SPEC 6.4 mode 2). No preview, no gate.
        raise FabError(f"gcode viewer produced no preview at {png}")
    fields = gcode.parse(text)
    return GcodeReport(
        gcode_path=str(gcode_path),
        preview_png=str(png),
        time_h=float(fields["time_h"]),
        filament_g=float(fields["filament_g"]),
        filament_mm=float(fields["filament_mm"]),
        layer_count=int(fields["layer_count"]),
        max_temp_c=float(fields["max_temp_c"]),
        retractions=int(fields["retractions"]),
        max_bridge_mm=float(fields["max_bridge_mm"]),
        support_volume_mm3=float(fields["support_volume_mm3"]),
        max_bed_temp_c=float(fields["max_bed_temp_c"]),
    )


async def estimate(gcode_path: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> dict[str, float]:
    """{time_h, filament_g, cost_try} straight from the slicer's own numbers."""
    del timeout_s  # pure parse, kept for the SPEC 6.3/6.4 "timeout on every call" rule
    fields = gcode.parse(_read_gcode(gcode_path))
    filament_g = float(fields["filament_g"])
    # PrusaSlicer prices the print from the profile's own filament_cost, which is
    # per material (PETG 950, ASA 1400, PA6-CF 3200 TRY/kg). The constant below is
    # only for G-code that carries no cost line.
    cost_try = float(fields["cost_try"]) or filament_g * FILAMENT_TRY_PER_G
    return {
        "time_h": float(fields["time_h"]),
        "filament_g": filament_g,
        "cost_try": round(cost_try, 2),
    }


async def upload(
    gcode_path: str, printer_id: str, timeout_s: float = DEFAULT_TIMEOUT_S
) -> FileHandle:
    """PUT /api/v1/files/usb/<name>. Never prints on upload - that needs approval."""
    base, key = _printer(printer_id)
    file = Path(gcode_path)
    if not file.is_file():
        raise FabError(f"gcode not found: {gcode_path}")
    payload = file.read_bytes()
    fields = gcode.parse(payload.decode(errors="replace"))
    filament_g = float(fields["filament_g"])
    if filament_g <= 0:
        # Without a weight the SPEC 14.4 budget cannot be charged, and a print that
        # silently overruns the budget defeats the budget.
        raise FabError(f"{file.name} declares no 'filament used [g]'; refusing to upload")
    await _request(
        "PUT",
        f"{base}/api/v1/files/usb/{file.name}",
        timeout_s,
        content=payload,
        headers={
            "X-Api-Key": key,
            "Content-Type": "application/octet-stream",
            "Print-After-Upload": "?0",  # SPEC 5.2: the approval gate decides, not the upload
            "Overwrite": "?1",
        },
    )
    return FileHandle(
        printer_id=printer_id,
        name=file.name,
        remote_path=f"usb/{file.name}",
        size_bytes=len(payload),
        filament_g=filament_g,
        time_h=float(fields["time_h"]),
        layer_count=int(fields["layer_count"]),
    )


async def start(
    file: FileHandle, printer_id: str, approval_token: str, timeout_s: float = DEFAULT_TIMEOUT_S
) -> JobHandle:
    """Start the print. SPEC 5.2 level 4: refuses without an approval token."""
    if not isinstance(approval_token, str) or not approval_token.strip():
        raise ApprovalRequiredError(
            "start() refused: SPEC 5.2 level 4 (MANUFACTURE) requires an approval token"
        )
    base, key = _printer(printer_id)
    # SPEC 14.4: 500 g of filament a day. Charged before the printer is touched,
    # refunded if it refuses, so an exhausted budget can never start a print.
    try:
        await _budget().consume(FILAMENT_BUDGET, file.filament_g)
    except RuntimeError as exc:  # BudgetExceeded; a bad resource name is a KeyError
        raise BudgetExhaustedError(f"start() refused: {exc}") from exc
    try:
        response = await _request(
            "POST",
            f"{base}/api/v1/job",
            timeout_s,
            json={"path": file.remote_path},  # the token stays in the lab, never on the printer
            headers={"X-Api-Key": key},
        )
    except FabError:
        await _budget().consume(FILAMENT_BUDGET, -file.filament_g)
        raise
    body = response.json() if response.content else {}
    job_id = str(body.get("id", ""))
    if not job_id:
        # PrusaLink answers POST /api/v1/job with 204 No Content; the id it assigned
        # only ever appears in GET /api/v1/status. Taking "" here would make
        # jobs.save() reject the name and leave a running print with no record -
        # exactly what T-095 must not produce.
        job_id = (await status(printer_id, timeout_s)).job_id or ""
    if not job_id:
        # The printer accepted the POST but reports no job: nothing is printing,
        # so the grams go back (SPEC 14.4).
        await _budget().consume(FILAMENT_BUDGET, -file.filament_g)
        raise FabError(f"{printer_id} accepted the job but reports none running")
    job = JobHandle(
        printer_id=printer_id,
        job_id=job_id,
        remote_path=file.remote_path,
        approval_token=approval_token,
    )
    # Written before the first poll: a connection dropped one second later must
    # still find the job on disk (SPEC 12.4 live tracking).
    jobs.save(
        _S.jobs_dir,
        jobs.JobRecord(
            job_id=job.job_id,
            printer_id=printer_id,
            remote_path=job.remote_path,
            approval_token=approval_token,
            filament_g=file.filament_g,
            layer_count=file.layer_count,
            state="printing",
        ),
    )
    return job


async def status(printer_id: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> PrinterStatus:
    """GET /api/v1/status - feeds SignalR PrintProgress (SPEC 12.4)."""
    base, key = _printer(printer_id)
    body = (
        await _request("GET", f"{base}/api/v1/status", timeout_s, headers={"X-Api-Key": key})
    ).json()
    printer = body.get("printer", {})
    job = body.get("job") or {}
    return PrinterStatus(
        printer_id=printer_id,
        state=str(printer.get("state", "UNKNOWN")),
        progress_pct=float(job.get("progress", 0.0)),
        job_id=str(job["id"]) if "id" in job else None,
        nozzle_c=float(printer.get("temp_nozzle", 0.0)),
        bed_c=float(printer.get("temp_bed", 0.0)),
        remaining_s=int(job.get("time_remaining", 0)),
    )


async def cancel(job: JobHandle, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
    """Stop a running job. Cancelling never needs approval."""
    base, key = _printer(job.printer_id)
    await _request(
        "DELETE", f"{base}/api/v1/job/{job.job_id}", timeout_s, headers={"X-Api-Key": key}
    )
    record = jobs.load(_S.jobs_dir, job.printer_id, job.job_id)
    if record is not None:  # the record is the audit trail; it is closed, not deleted
        record.state = "cancelled"
        jobs.save(_S.jobs_dir, record)


# --- T-095 live tracking ----------------------------------------------------


async def reconcile(printer_id: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> jobs.JobRecord | None:
    """Re-attach to whatever the printer is printing, without duplicating the job.

    Called on every poll and after every reconnect: an existing record for the
    printer's job id is updated in place, and only a job this process never saw
    (brain restarted mid-print) gets a new, `adopted` record.
    """
    state = await status(printer_id, timeout_s)
    if state.job_id is None:
        return None
    record = jobs.load(_S.jobs_dir, printer_id, state.job_id) or jobs.JobRecord(
        job_id=state.job_id,
        printer_id=printer_id,
        remote_path="",
        # An adopted job carries no token: the SPEC 5.2 approval was granted in a
        # process that is gone. Blank, never invented.
        approval_token="",  # nosec B106 - an empty field, not a credential
        adopted=True,
    )
    record.state = state.state
    record.pct = state.progress_pct
    record.nozzle_c = state.nozzle_c
    record.bed_c = state.bed_c
    record.remaining_s = state.remaining_s
    jobs.save(_S.jobs_dir, record)
    return record


async def poll(printer_id: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """One status poll as the SPEC 9.4 PrintProgress payload; empty when idle.

    Not an MCP tool: SPEC 6.4 closes the fab contract at seven functions. The lab
    process imports this and forwards each payload to the SignalR event.
    """
    record = await reconcile(printer_id, timeout_s)
    return {} if record is None else jobs.progress(record)


async def track(
    printer_id: str,
    on_progress: Callable[[dict[str, Any]], None],
    interval_s: float = jobs.POLL_INTERVAL_S,
    max_drops: int = 12,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> jobs.JobRecord | None:
    """Poll until the print ends, handing every tick to `on_progress` (SPEC 12.4).

    Not an MCP tool: it outlives the SPEC 6.5 client timeout by design. The lab
    process runs it and forwards each payload to the SignalR PrintProgress event.
    A dropped connection is retried, never fatal - the record on disk is the job.
    """
    drops = 0
    while True:
        try:
            record = await reconcile(printer_id, timeout_s)
        except FabError:
            drops += 1
            if drops >= max_drops:
                raise
            await asyncio.sleep(interval_s)
            continue
        drops = 0
        if record is None:
            return None
        on_progress(jobs.progress(record))
        if not jobs.is_active(record):
            return record
        await asyncio.sleep(interval_s)


# --- T-096 quality control --------------------------------------------------


@dataclass
class QcReport:
    print_job_id: str
    profile_id: str
    verdict: str  # pass | fail
    failures: list[str]
    deviation_mm: float
    direction: int
    compensation_mm: float | None  # set when SPEC 12.5's systematic rule fired
    genome_updated: bool


async def _store_qc(print_job_id: str, payload: dict[str, Any]) -> str:
    """Write print_jobs.qc (SPEC 7) and return the profile the part was printed with."""
    async with _sessions()() as session:
        profile = (
            await session.execute(_SELECT_PROFILE, {"id": print_job_id})
        ).scalar_one_or_none()
        if profile is None:
            raise FabError(f"no print_jobs row for {print_job_id}")
        await session.execute(_UPDATE_QC, {"id": print_job_id, "qc": json.dumps(payload)})
        await session.commit()
    return str(profile)


async def submit_qc(
    print_job_id: str,
    form: qc.QcForm,
    genome_id: str = "",
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> QcReport:
    """The SPEC 12.5 quality form: store it, write the mass back, compensate a trend."""
    del timeout_s  # local files plus one short transaction
    verdict = qc.evaluate(form)
    payload: dict[str, Any] = {
        "verdict": "pass" if verdict.passed else "fail",
        "failures": verdict.failures,
        "deviation_mm": verdict.deviation_mm,
        "direction": verdict.direction,
        "measurements": dataclasses.asdict(form),
    }
    profile_id = await _store_qc(print_job_id, payload)

    genome_updated = False
    if verdict.passed and genome_id:
        # SPEC 13.3: body_mass_kg is the MEASURED value. body_mass_cad_kg is the CAD
        # estimate and quality control never touches it.
        genome = await genome_server.read(genome_id)
        genome["mechanical"]["body_mass_kg"] = round(form.mass_measured_g / 1000.0, 4)
        await genome_server.write(genome)
        genome_updated = True

    qc.append_history(_S.jobs_dir, profile_id, print_job_id, verdict)
    deviation = qc.systematic_deviation(_S.jobs_dir, profile_id)
    compensation: float | None = None
    if deviation is not None:
        old, new = qc.apply_compensation(_S.profile_dir / f"{profile_id}.ini", deviation)
        qc.mark_compensated(_S.jobs_dir, profile_id, new - old)
        compensation = new
        await _audit_compensation(profile_id, print_job_id, deviation, old, new)

    return QcReport(
        print_job_id=print_job_id,
        profile_id=profile_id,
        verdict=payload["verdict"],
        failures=verdict.failures,
        deviation_mm=verdict.deviation_mm,
        direction=verdict.direction,
        compensation_mm=compensation,
        genome_updated=genome_updated,
    )


async def _audit_compensation(
    profile_id: str, print_job_id: str, deviation: float, old: float, new: float
) -> None:
    """SPEC 12.5: an automatic compensation change goes to audit_log.

    audit_log stores a hash of the parameters, never the values (SPEC 5.4), so the
    numbers a human needs to read back go in `outcome`.
    """
    from neml_brain.runtime.audit import AuditLog

    await AuditLog(_sessions()).write(
        actor="neml-mcp-fab",
        action="slicer.compensation_updated",
        target=profile_id,
        params={"print_job_id": print_job_id, "deviation_mm": deviation},
        outcome=(
            f"{qc.COMPENSATION_KEY} {old} -> {new} after {qc.STREAK} consecutive parts"
            f" deviating {deviation:+.3f} mm"
        ),
    )


# SPEC 6.4 lists exactly these seven and the contract is closed: brain's
# test_no_extra_tools pins the set. `track`, `poll`, `reconcile` and `submit_qc`
# are pipeline steps of SPEC 12.4/12.5, not SPEC 6.4 tools - the lab process
# imports them, the same way it already had to for `track`.
TOOLS: dict[str, Callable[..., Any]] = {
    "slice": slice,
    "validate_gcode": validate_gcode,
    "estimate": estimate,
    "upload": upload,
    "start": start,
    "status": status,
    "cancel": cancel,
}

app = make_app("neml-mcp-fab", VERSION, TOOLS)

if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT)
