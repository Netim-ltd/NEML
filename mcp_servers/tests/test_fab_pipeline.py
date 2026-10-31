# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""T-095 live tracking and T-096 quality control for neml-mcp-fab.

The invariants worth a test here are the ones that cost real money or real parts:
  * a dropped printer connection must not lose or duplicate the job record;
  * SPEC 12.5's systematic-deviation rule fires on the third consecutive part in
    the same direction - not the second, and not again on the fourth;
  * a QC pass writes the MEASURED mass to genome mechanical.body_mass_kg and
    never touches the CAD estimate body_mass_cad_kg (SPEC 13.3).

PrusaLink and PrusaSlicer are doubles: nothing here talks to a printer.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

from mcp_servers.neml_mcp_fab import jobs, qc, server
from mcp_servers.neml_mcp_genome import server as genome_server
from mcp_servers.tests.test_fab import Budget

REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE = "petg_0.20_structural"


def call(coro: Any) -> Any:
    return asyncio.run(coro)


# --- doubles ----------------------------------------------------------------


class FakePrinter:
    """PrusaLink: a scripted reply per request. An Exception entry drops the line."""

    def __init__(self, *replies: dict[str, Any] | Exception) -> None:
        self.replies = list(replies)
        self.requests: list[httpx.Request] = []

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return httpx.Response(200, json=reply)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self._handle))


def printing(pct: float, state: str = "PRINTING", job_id: int = 42) -> dict[str, Any]:
    return {
        "printer": {"state": state, "temp_nozzle": 240.0, "temp_bed": 85.0},
        "job": {"id": job_id, "progress": pct, "time_remaining": 1800},
    }


class FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class FakeDb:
    """Session factory, session and async context manager in one object.

    Matches the slice of AsyncSession that neml_brain.runtime.audit.Session declares,
    which is all `_store_qc` and the audit write use.
    """

    def __init__(self, profile_id: str | None = PROFILE) -> None:
        self.profile_id = profile_id
        self.statements: list[tuple[str, Any]] = []
        self.commits = 0

    def __call__(self) -> FakeDb:
        return self

    async def __aenter__(self) -> FakeDb:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def execute(self, statement: Any, parameters: Any = None) -> FakeResult:
        self.statements.append((str(statement), parameters))
        return FakeResult(self.profile_id)

    async def commit(self) -> None:
        self.commits += 1

    def sql(self, needle: str) -> list[Any]:
        return [params for text, params in self.statements if needle in text]


@pytest.fixture
def printer_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRUSALINK_URL", "http://printer.test")
    monkeypatch.setenv("PRUSALINK_API_KEY", "test-key")


@pytest.fixture
def profiles(tmp_path: Path) -> Path:
    """A scratch copy of the real slicer profiles; compensation rewrites them."""
    out = tmp_path / "profiles"
    out.mkdir()
    shutil.copy(REPO_ROOT / "manufacturing" / "slicer_profiles" / f"{PROFILE}.ini", out)
    return out


@pytest.fixture
def genome_dir(tmp_path: Path) -> Path:
    """The SPEC 13.3 seed genome plus the parent it claims, in a scratch directory."""
    src = REPO_ROOT / "hardware" / "genome"
    out = tmp_path / "genome"
    out.mkdir()
    shutil.copy(src / "genome.schema.json", out / "genome.schema.json")
    genome = dict(yaml.safe_load((src / "quadruped_v2.yaml").read_text(encoding="utf-8")))
    genome["mechanical"]["body_mass_kg"] = 2.0  # stale measurement, QC replaces it
    (out / "quadruped_v2.yaml").write_text(yaml.safe_dump(genome), encoding="utf-8")
    parent = dict(genome)
    parent["genome_id"] = "quadruped_v1"
    parent.pop("parent")
    (out / "quadruped_v1.yaml").write_text(yaml.safe_dump(parent), encoding="utf-8")
    genome_server.configure(genome_dir=out)
    return out


def form(deviation_mm: float = 0.0, mass_g: float = 2400.0) -> qc.QcForm:
    """A passing SPEC 12.5 form, offset by `deviation_mm` on all three dimensions."""
    return qc.QcForm(
        dim_nominal_mm=[120.0, 28.0, 32.0],
        dim_measured_mm=[120.0 + deviation_mm, 28.0 + deviation_mm, 32.0 + deviation_mm],
        hole_gauge_pass=True,
        mass_cad_g=2310.0,  # SPEC 13.3 body_mass_cad_kg
        mass_measured_g=mass_g,
        layer_adhesion_pass=True,
        warp_mm=0.2,
    )


# --- T-095: live tracking ---------------------------------------------------


def test_poll_emits_the_signalr_printprogress_payload(printer_env: None, tmp_path: Path) -> None:
    """SPEC 9.4 PrintProgress: exactly these six fields."""
    server.configure(http=FakePrinter(printing(50.0)).client(), jobs_dir=tmp_path)
    jobs.save(
        tmp_path,
        jobs.JobRecord("42", "prusa-01", "usb/p.gcode", "approval-1", layer_count=200),
    )

    payload = call(server.poll("prusa-01"))

    assert payload == {
        "jobId": "42",
        "pct": 50.0,
        "layer": 100,  # PrusaLink /status carries no layer; derived from pct x layers
        "etaMin": 30,
        "nozzleC": 240.0,
        "bedC": 85.0,
    }


def test_reconnect_does_not_duplicate_the_job(printer_env: None, tmp_path: Path) -> None:
    """The record written by start() is the job. Reconnecting updates it in place."""

    server.configure(
        http=FakePrinter({"id": 42}, printing(10.0), printing(20.0)).client(),
        jobs_dir=tmp_path,
        budget=Budget(),
    )
    handle = server.FileHandle("prusa-01", "p.gcode", "usb/p.gcode", 9, 12.5, 1.5, 200)

    call(server.start(handle, "prusa-01", "approval-1"))
    first = call(server.reconcile("prusa-01"))
    second = call(server.reconcile("prusa-01"))

    assert len(list(tmp_path.glob("*.json"))) == 1
    assert first is not None and second is not None
    assert (first.job_id, second.job_id) == ("42", "42")
    assert second.adopted is False  # started here, not found on the printer
    assert second.approval_token == "approval-1"  # noqa: S105 - a token, not a secret
    assert second.pct == 20.0


def test_start_takes_the_job_id_from_status_when_prusalink_answers_204(
    printer_env: None, tmp_path: Path
) -> None:
    """PrusaLink answers POST /api/v1/job with 204 and no body. Dropping the id
    there would leave a running print with no record, which is the one thing
    T-095 must not do."""

    class Empty(FakePrinter):
        def _handle(self, request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            if request.method == "POST":
                return httpx.Response(204)
            return httpx.Response(200, json=printing(0.0, job_id=77))

    server.configure(http=Empty({}).client(), jobs_dir=tmp_path, budget=Budget())
    handle = server.FileHandle("prusa-01", "p.gcode", "usb/p.gcode", 9, 12.5, 1.5, 200)

    job = call(server.start(handle, "prusa-01", "approval-1"))

    assert job.job_id == "77"
    assert (tmp_path / "prusa-01__77.json").is_file()


def test_start_refunds_the_budget_when_no_job_is_running(printer_env: None, tmp_path: Path) -> None:
    """Printer took the POST but reports nothing printing: the grams go back."""

    class Idle(FakePrinter):
        def _handle(self, request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            if request.method == "POST":
                return httpx.Response(204)
            return httpx.Response(200, json={"printer": {"state": "IDLE"}, "job": None})

    budget = Budget()
    server.configure(http=Idle({}).client(), jobs_dir=tmp_path, budget=budget)
    handle = server.FileHandle("prusa-01", "p.gcode", "usb/p.gcode", 9, 12.5, 1.5, 200)

    with pytest.raises(server.FabError):
        call(server.start(handle, "prusa-01", "approval-1"))

    assert call(budget.used("filament_grams")) == 0.0
    assert list(tmp_path.glob("*.json")) == []


def test_a_record_written_by_start_still_reads_as_active(tmp_path: Path) -> None:
    """start() writes the SPEC 7 print_jobs vocabulary, reconcile() writes what
    PrusaLink shouts. Matching only one of the two ends tracking on the first tick."""
    assert jobs.is_active(jobs.JobRecord("1", "p", "", "", state="printing"))
    assert jobs.is_active(jobs.JobRecord("1", "p", "", "", state="PRINTING"))
    assert not jobs.is_active(jobs.JobRecord("1", "p", "", "", state="FINISHED"))


def test_a_job_started_before_this_process_is_adopted_once(
    printer_env: None, tmp_path: Path
) -> None:
    """Brain restarted mid-print: the job is picked up, and only once."""
    server.configure(http=FakePrinter(printing(70.0)).client(), jobs_dir=tmp_path)

    first = call(server.reconcile("prusa-01"))
    call(server.reconcile("prusa-01"))

    assert first is not None and first.adopted is True
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_track_survives_a_dropped_connection(printer_env: None, tmp_path: Path) -> None:
    """SPEC 12.4 live tracking: the printer going away is a retry, not a lost job."""
    printer = FakePrinter(
        printing(10.0),
        httpx.ConnectError("printer unplugged"),
        printing(60.0),
        printing(100.0, state="FINISHED"),
    )
    server.configure(http=printer.client(), jobs_dir=tmp_path)
    jobs.save(tmp_path, jobs.JobRecord("42", "prusa-01", "usb/p.gcode", "a", layer_count=100))
    ticks: list[dict[str, Any]] = []

    record = call(server.track("prusa-01", ticks.append, interval_s=0.0))

    assert [t["pct"] for t in ticks] == [10.0, 60.0, 100.0]
    assert record is not None and record.state == "FINISHED"
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_track_gives_up_after_too_many_drops(printer_env: None, tmp_path: Path) -> None:
    server.configure(http=FakePrinter(httpx.ConnectError("gone")).client(), jobs_dir=tmp_path)
    jobs.save(tmp_path, jobs.JobRecord("42", "prusa-01", "usb/p.gcode", "a"))

    with pytest.raises(server.FabError):
        call(server.track("prusa-01", lambda _: None, interval_s=0.0, max_drops=3))

    assert (tmp_path / "prusa-01__42.json").is_file()  # the job record is still there


def test_a_printer_job_id_is_never_trusted_as_a_file_name(tmp_path: Path) -> None:
    with pytest.raises(jobs.JobRecordError):
        jobs.path(tmp_path, "prusa-01", "../../etc/passwd")


# --- T-096: quality control -------------------------------------------------


def test_the_spec_125_thresholds() -> None:
    assert qc.evaluate(form(0.2)).passed
    assert not qc.evaluate(form(0.4)).passed  # caliper, +/-0.3 mm
    assert not qc.evaluate(form(mass_g=2000.0)).passed  # scale, +/-5% of CAD
    bad = qc.QcForm(**{**vars(form()), "warp_mm": 0.8})
    assert not qc.evaluate(bad).passed
    assert qc.evaluate(qc.QcForm(**{**vars(form()), "hole_gauge_pass": False})).failures == [
        "hole gauge: fail"
    ]
    with pytest.raises(qc.QcError):
        qc.evaluate(qc.QcForm(dim_nominal_mm=[1.0], dim_measured_mm=[1.0], mass_cad_g=1.0))


def test_qc_is_stored_on_the_print_job_row(tmp_path: Path, profiles: Path) -> None:
    db = FakeDb()
    server.configure(jobs_dir=tmp_path, profile_dir=profiles, session_factory=db)

    report = call(server.submit_qc("11111111-1111-1111-1111-111111111111", form(0.1)))

    assert report.verdict == "pass"
    stored = db.sql("UPDATE print_jobs")[0]
    assert stored["id"] == "11111111-1111-1111-1111-111111111111"
    assert '"verdict": "pass"' in stored["qc"]
    assert db.commits == 1


def test_qc_on_an_unknown_print_job_is_refused(tmp_path: Path, profiles: Path) -> None:
    server.configure(jobs_dir=tmp_path, profile_dir=profiles, session_factory=FakeDb(None))
    with pytest.raises(server.FabError):
        call(server.submit_qc("no-such-job", form()))


def test_systematic_deviation_fires_on_the_third_part_and_not_the_second(
    tmp_path: Path, profiles: Path
) -> None:
    """SPEC 12.5: three consecutive parts in the same direction, then compensate."""
    db = FakeDb()
    server.configure(jobs_dir=tmp_path, profile_dir=profiles, session_factory=db)
    ini = profiles / f"{PROFILE}.ini"

    first = call(server.submit_qc("job-1", form(0.2)))
    second = call(server.submit_qc("job-2", form(0.2)))
    assert (first.compensation_mm, second.compensation_mm) == (None, None)
    assert f"{qc.COMPENSATION_KEY} = 0" in ini.read_text(encoding="utf-8")

    third = call(server.submit_qc("job-3", form(0.2)))

    # Parts came out 0.2 mm oversized; every contour moves in by half of that.
    assert third.compensation_mm == -0.1
    assert f"{qc.COMPENSATION_KEY} = -0.1" in ini.read_text(encoding="utf-8")
    # SPEC 12.5: the change is written to audit_log.
    audit = db.sql("INSERT INTO audit_log")[0]
    assert audit["action"] == "slicer.compensation_updated"
    assert audit["target"] == PROFILE
    assert "-> -0.1" in audit["outcome"]

    # and it does not fire again on the next part: the run restarts after a change.
    assert call(server.submit_qc("job-4", form(0.2))).compensation_mm is None


def test_a_direction_change_breaks_the_run(tmp_path: Path, profiles: Path) -> None:
    server.configure(jobs_dir=tmp_path, profile_dir=profiles, session_factory=FakeDb())
    for i, deviation in enumerate((0.2, -0.2, 0.2)):
        report = call(server.submit_qc(f"job-{i}", form(deviation)))
    assert report.compensation_mm is None


def test_one_part_measured_three_times_is_not_a_trend(tmp_path: Path, profiles: Path) -> None:
    """SPEC 12.5 counts PARTS. A re-measured part replaces its own earlier reading;
    three submissions of one form must not move the compensation."""
    server.configure(jobs_dir=tmp_path, profile_dir=profiles, session_factory=FakeDb())

    for _ in range(3):
        report = call(server.submit_qc("job-1", form(0.2)))

    assert report.compensation_mm is None
    ini = (profiles / f"{PROFILE}.ini").read_text(encoding="utf-8")
    assert f"{qc.COMPENSATION_KEY} = 0" in ini


def test_compensation_is_clamped(tmp_path: Path, profiles: Path) -> None:
    """A runaway correction would quietly scrap every part that follows."""
    ini = profiles / f"{PROFILE}.ini"
    qc.apply_compensation(ini, 40.0)
    assert float(qc.apply_compensation(ini, 40.0)[1]) == -qc.MAX_COMPENSATION_MM


def test_qc_pass_writes_the_measured_mass_into_the_genome(
    tmp_path: Path, profiles: Path, genome_dir: Path
) -> None:
    """SPEC 13.3: body_mass_kg is MEASURED, body_mass_cad_kg is the CAD estimate."""
    server.configure(jobs_dir=tmp_path, profile_dir=profiles, session_factory=FakeDb())

    report = call(server.submit_qc("job-1", form(0.1, mass_g=2400.0), genome_id="quadruped_v2"))

    stored = yaml.safe_load((genome_dir / "quadruped_v2.yaml").read_text(encoding="utf-8"))
    assert report.genome_updated is True
    assert stored["mechanical"]["body_mass_kg"] == 2.40
    assert stored["mechanical"]["body_mass_cad_kg"] == 2.31  # untouched by QC
    assert stored["limits"]["joint_torque_nm_max"] == 2.5  # SPEC 13.3 stays locked


def test_a_failed_part_never_reaches_the_genome(
    tmp_path: Path, profiles: Path, genome_dir: Path
) -> None:
    server.configure(jobs_dir=tmp_path, profile_dir=profiles, session_factory=FakeDb())

    report = call(server.submit_qc("job-1", form(0.5), genome_id="quadruped_v2"))

    assert report.verdict == "fail" and report.genome_updated is False
    stored = yaml.safe_load((genome_dir / "quadruped_v2.yaml").read_text(encoding="utf-8"))
    assert stored["mechanical"]["body_mass_kg"] == 2.0  # the stale value, untouched
