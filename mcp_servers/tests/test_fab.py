# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for neml-mcp-fab (SPEC 6.4).

The two invariants nothing else guards:
  * SPEC 5.2 level 4 - `start` refuses without a human approval token, and the
    token never leaves the lab.
  * SPEC 1.3 - PrusaSlicer and the G-code viewer are only ever argv, never an
    import.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest

from mcp_servers.neml_mcp_fab import gcode, server


def call(coro: Any) -> Any:
    return asyncio.run(coro)


class Budget:
    """In-memory async budget double for printer protocol tests."""

    def __init__(self) -> None:
        self.amount = 0.0

    async def consume(self, resource: str, amount: float) -> float:
        assert resource == "filament_grams"
        if self.amount + amount > 500.0:
            raise RuntimeError("filament budget exhausted")
        self.amount += amount
        return self.amount / 500.0

    async def used(self, resource: str) -> float:
        assert resource == "filament_grams"
        return self.amount


class FakeRunner:
    """Records argv instead of running anything; can pretend to emit a file."""

    def __init__(self, emits: Path | None = None) -> None:
        self.calls: list[list[str]] = []
        self.emits = emits

    async def __call__(self, argv: list[str], timeout_s: float) -> str:
        self.calls.append(argv)
        if self.emits is not None:
            self.emits.write_bytes(b"; fake gcode\n")
        return ""


@pytest.fixture
def printer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRUSALINK_URL", "http://printer.test")
    monkeypatch.setenv("PRUSALINK_API_KEY", "test-key")


def mock_http(requests: list[httpx.Request], body: dict[str, Any]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- SPEC 5.2 level 4: the approval gate -----------------------------------


@pytest.mark.parametrize("token", ["", "   "])
def test_start_refuses_without_an_approval_token(
    printer: None, token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests: list[httpx.Request] = []
    server.configure(http=mock_http(requests, {"id": 7}))
    handle = server.FileHandle("prusa-01", "part.gcode", "usb/part.gcode", 12)

    with pytest.raises(server.ApprovalRequiredError):
        call(server.start(handle, "prusa-01", token))

    assert requests == []  # refused before the printer was ever contacted


def test_start_refuses_when_the_filament_budget_is_exhausted(printer: None, tmp_path: Path) -> None:
    """SPEC 14.4: 500 g a day. The real Budget, so a renamed resource fails here."""
    requests: list[httpx.Request] = []
    budget = Budget()
    call(budget.consume("filament_grams", 480.0))
    server.configure(http=mock_http(requests, {"id": 1}), jobs_dir=tmp_path, budget=budget)
    handle = server.FileHandle("prusa-01", "part.gcode", "usb/part.gcode", 12, filament_g=40.0)

    with pytest.raises(server.BudgetExhaustedError):
        call(server.start(handle, "prusa-01", "approval-abc"))

    assert requests == []  # the printer is never asked
    assert call(budget.used("filament_grams")) == 480.0  # and nothing was charged
    assert list(tmp_path.glob("*.json")) == []  # no job record for a print that never ran


def test_start_charges_the_filament_budget(printer: None, tmp_path: Path) -> None:
    budget = Budget()
    server.configure(http=mock_http([], {"id": 1}), jobs_dir=tmp_path, budget=budget)
    handle = server.FileHandle("prusa-01", "part.gcode", "usb/part.gcode", 12, filament_g=40.0)

    call(server.start(handle, "prusa-01", "approval-abc"))

    assert call(budget.used("filament_grams")) == 40.0


def test_start_keeps_the_approval_token_out_of_the_printer_request(
    printer: None, tmp_path: Path
) -> None:
    requests: list[httpx.Request] = []
    server.configure(http=mock_http(requests, {"id": "job-9"}), jobs_dir=tmp_path, budget=Budget())
    handle = server.FileHandle("prusa-01", "part.gcode", "usb/part.gcode", 12)

    job = call(server.start(handle, "prusa-01", "approval-abc"))

    assert job.job_id == "job-9"
    assert job.approval_token == "approval-abc"  # noqa: S105 - a token, not a secret
    assert len(requests) == 1
    assert requests[0].url.path == "/api/v1/job"
    assert b"approval-abc" not in requests[0].content


def test_upload_never_prints_on_its_own(printer: None, tmp_path: Path) -> None:
    requests: list[httpx.Request] = []
    server.configure(http=mock_http(requests, {}))
    gcode_file = tmp_path / "part.gcode"
    gcode_file.write_text(SAMPLE, encoding="utf-8")

    handle = call(server.upload(str(gcode_file), "prusa-01"))

    assert handle.remote_path == "usb/part.gcode"
    assert requests[0].headers["Print-After-Upload"] == "?0"
    # start() charges the SPEC 14.4 budget with these, so upload has to read them.
    assert handle.filament_g == 12.5
    assert handle.layer_count == 3


def test_upload_refuses_gcode_that_declares_no_weight(printer: None, tmp_path: Path) -> None:
    """A print whose filament is unknown cannot be charged to the SPEC 14.4 budget."""
    requests: list[httpx.Request] = []
    server.configure(http=mock_http(requests, {}))
    gcode_file = tmp_path / "part.gcode"
    gcode_file.write_text("; hello\n", encoding="utf-8")

    with pytest.raises(server.FabError):
        call(server.upload(str(gcode_file), "prusa-01"))
    assert requests == []


def test_printer_without_credentials_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PRUSALINK_URL", raising=False)
    monkeypatch.delenv("PRUSALINK_API_KEY", raising=False)
    with pytest.raises(server.FabError):
        call(server.status("prusa-01"))


# --- SPEC 1.3: the AGPL tools stay outside the process ----------------------


def test_slice_calls_prusaslicer_as_a_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = tmp_path / "part.3mf"
    model.write_bytes(b"3mf")
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "pla_0.25_draft.ini").write_text("layer_height = 0.25\n", encoding="utf-8")
    work = tmp_path / "work"
    runner = FakeRunner(emits=work / "part__pla_0.25_draft.gcode")
    work.mkdir()
    monkeypatch.setenv("PRUSASLICER_BIN", "/usr/bin/prusa-slicer")
    server.configure(runner=runner, work_dir=work, profile_dir=profiles)

    result = call(server.slice(str(model), "pla_0.25_draft"))

    assert runner.calls[0][0] == "/usr/bin/prusa-slicer"
    assert "--export-gcode" in runner.calls[0]
    assert len(result.sha256) == 64


def test_validate_gcode_returns_the_png_the_approval_screen_shows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SPEC 6.4 mode 2: the operator approves the print by looking at this file."""
    gcode_file = tmp_path / "part.gcode"
    gcode_file.write_text(SAMPLE, encoding="utf-8")
    png = tmp_path / "part.png"
    runner = FakeRunner(emits=png)
    monkeypatch.setenv("PRUSA_GCODEVIEWER_BIN", "/usr/bin/prusa-gcodeviewer")
    server.configure(runner=runner)

    report = call(server.validate_gcode(str(gcode_file)))

    assert runner.calls[0] == [
        "/usr/bin/prusa-gcodeviewer",
        "--export-png",
        str(png),
        str(gcode_file),
    ]
    assert report.preview_png == str(png)
    assert Path(report.preview_png).is_file()
    assert (report.layer_count, report.retractions) == (3, 2)
    assert (report.filament_g, report.filament_mm) == (12.5, 4210.0)
    assert report.time_h == pytest.approx(1.5)
    assert report.max_temp_c == 215
    assert report.max_bridge_mm == pytest.approx(20.0)
    assert report.support_volume_mm3 > 0


def test_validate_gcode_refuses_when_the_viewer_produced_no_png(tmp_path: Path) -> None:
    gcode_file = tmp_path / "part.gcode"
    gcode_file.write_text(SAMPLE, encoding="utf-8")
    server.configure(runner=FakeRunner())  # exits 0, writes nothing

    with pytest.raises(server.FabError):
        call(server.validate_gcode(str(gcode_file)))


def test_slice_refuses_an_unknown_profile(tmp_path: Path) -> None:
    model = tmp_path / "part.3mf"
    model.write_bytes(b"3mf")
    server.configure(runner=FakeRunner(), work_dir=tmp_path, profile_dir=tmp_path / "none")
    with pytest.raises(server.FabError):
        call(server.slice(str(model), "no_such_profile"))


def test_slice_refuses_a_missing_model(tmp_path: Path) -> None:
    server.configure(runner=FakeRunner(), work_dir=tmp_path, profile_dir=tmp_path)
    with pytest.raises(server.FabError):
        call(server.slice(str(tmp_path / "gone.3mf"), "pla_0.25_draft"))


# --- the G-code analyser ----------------------------------------------------

SAMPLE = """
; total layers count = 3
; filament used [g] = 12.5
; filament used [mm] = 4210.0
; estimated printing time (normal mode) = 1h 30m 0s
M109 S215
M190 S80
M83
G1 X0 Y0
;TYPE:Bridge infill
G1 X0 Y20 E1.0
;TYPE:Support material
G1 X0 Y5 E0.5
;TYPE:Perimeter
G1 E-0.8
G1 E-0.8
"""


def test_parse_reads_every_quantity_spec_64_lists() -> None:
    """SPEC 6.4: time, filament (g/mm), layer count, max temperature, retraction
    count, bridge lengths, support volume. All seven, or the approval screen lies."""
    fields = gcode.parse(SAMPLE)
    assert fields["layer_count"] == 3
    assert fields["filament_g"] == 12.5
    assert fields["filament_mm"] == 4210.0
    assert fields["time_h"] == pytest.approx(1.5)
    assert fields["max_temp_c"] == 215
    assert fields["max_bed_temp_c"] == 80
    assert fields["retractions"] == 2
    assert fields["max_bridge_mm"] == pytest.approx(20.0)
    assert fields["support_volume_mm3"] > 0


def test_estimate_prices_the_print_from_the_slicers_own_number(tmp_path: Path) -> None:
    """PrusaSlicer prices from the profile's filament_cost, which is per material
    (PETG 950, ASA 1400, PA6-CF 3200 TRY/kg). One lab-wide constant is not."""
    path = tmp_path / "part.gcode"
    path.write_text(SAMPLE + "; filament cost = 11.88\n", encoding="utf-8")
    out = call(server.estimate(str(path)))
    assert out["filament_g"] == 12.5
    assert out["cost_try"] == pytest.approx(11.88)


def test_estimate_falls_back_when_the_gcode_declares_no_cost(tmp_path: Path) -> None:
    path = tmp_path / "part.gcode"
    path.write_text(SAMPLE, encoding="utf-8")
    out = call(server.estimate(str(path)))
    assert out["cost_try"] == pytest.approx(12.5 * server.FILAMENT_TRY_PER_G, abs=0.01)


def test_estimate_refuses_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(server.FabError):
        call(server.estimate(str(tmp_path / "gone.gcode")))
