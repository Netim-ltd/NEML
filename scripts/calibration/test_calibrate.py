# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the SPEC 11.3 calibration driver (T-076, T-077).

The brain is replaced by an httpx MockTransport, so what is tested is what this
script is responsible for: the 5 x 10 schedule, deterministic seeds, the
aggregation over repetitions, and the gap exit codes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import calibrate
import httpx
import pytest
from neml_brain.evolution.reality_gap import MANOEUVRES, REPEATS

# Values a sim run reports for each manoeuvre; every measure SPEC 11.3 asks for.
# The tests patch `calibrate.httpx.Client` - which is the httpx module itself -
# so the fake client has to be built from the class captured before the patch,
# or it would construct itself forever.
REAL_CLIENT = httpx.Client

SIM_METRICS: dict[str, dict[str, float]] = {
    "M1_straight": {"deviation_m": 0.100, "energy_wh": 2.0, "duration_s": 10.0},
    "M2_turn": {"angle_error_deg": 4.0, "energy_wh": 1.0},
    "M3_step": {"success": 1.0, "max_joint_torque_nm": 2.0},
    "M4_stand": {"body_sway_rms_mm": 3.0},
    "M5_payload": {"deviation_m": 0.200, "energy_wh": 3.0},
}


def _sim_brain(record: list[dict[str, Any]]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/sim/run"
        body = json.loads(request.content)
        record.append(body)
        return httpx.Response(201, json={"metrics": SIM_METRICS[body["skill_id"]]})

    return REAL_CLIENT(transport=httpx.MockTransport(handler), base_url="http://brain")


def _real_brain() -> httpx.Client:
    """The robot side: create a task, wait for it, read the run's metrics."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            manoeuvre_id = json.loads(request.content)["spec"]["manoeuvre"]
            return httpx.Response(201, json={"id": manoeuvre_id})
        if path.endswith("/runs"):
            manoeuvre_id = path.split("/")[3]
            return httpx.Response(200, json=[{"metrics": SIM_METRICS[manoeuvre_id]}])
        return httpx.Response(200, json={"state": "succeeded"})

    return REAL_CLIENT(transport=httpx.MockTransport(handler), base_url="http://brain")


def test_run_side_does_five_manoeuvres_ten_times(monkeypatch: pytest.MonkeyPatch) -> None:
    record: list[dict[str, Any]] = []
    monkeypatch.setattr(calibrate.httpx, "Client", lambda **kw: _sim_brain(record))

    data = calibrate.run_side("sim", None, "http://brain")

    assert len(record) == len(MANOEUVRES) * REPEATS == 50
    assert set(data["manoeuvres"]) == {m.id for m in MANOEUVRES}
    assert all(len(reps) == REPEATS for reps in data["repetitions"].values())
    assert {body["profile"] for body in record} == {"fast"}  # SPEC 4.5


def test_seeds_are_unique_and_reproducible(monkeypatch: pytest.MonkeyPatch) -> None:
    record: list[dict[str, Any]] = []
    monkeypatch.setattr(calibrate.httpx, "Client", lambda **kw: _sim_brain(record))
    calibrate.run_side("sim", None, "http://brain")

    seeds = [body["seed"] for body in record]
    assert len(set(seeds)) == 50, "a repeated seed would repeat the run, not repeat the measurement"
    assert seeds[0] == calibrate.seed_for(0, 0)
    assert calibrate.seed_for(3, 7) == calibrate.SEED_BASE + 307


def test_aggregate_takes_the_median() -> None:
    """One bad repetition out of ten must not move the calibration."""
    reps = [{"deviation_m": 0.10} for _ in range(9)] + [{"deviation_m": 9.99}]
    assert calibrate.aggregate(reps) == {"deviation_m": 0.10}


def test_missing_measure_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"metrics": {"energy_wh": 1.0}})  # no deviation_m

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://brain")
    with pytest.raises(SystemExit, match="deviation_m"):
        calibrate.sim_once(client, "M1_straight", 1)


def test_both_sides_report_the_same_measure_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """The point of the protocol: sim and reality are directly comparable.

    Both sides go through measure_once(), so whatever the transport underneath,
    the keys that come out are the SPEC 11.3 measures for that manoeuvre - which
    is exactly what the gap formula subtracts.
    """
    sim_client = _sim_brain([])
    real_client = _real_brain()
    for index, manoeuvre in enumerate(MANOEUVRES):
        in_sim = calibrate.measure_once(sim_client, "sim", None, index, 0)
        in_real = calibrate.measure_once(real_client, "real", "quad-01", index, 0)
        assert set(in_sim) == set(in_real) == set(manoeuvre.measures)


def test_fit_refuses_when_the_brain_drops_the_physics_block() -> None:
    """Without the physics in the request, every iteration simulates the same
    thing and the fit is meaningless - that must be loud, not silent."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"metrics": SIM_METRICS["M1_straight"]})

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://brain")
    with pytest.raises(SystemExit, match="physics"):
        calibrate.sim_once(client, "M1_straight", 1, calibrate.PhysicsParams())


def _write(path: Path, manoeuvres: dict[str, dict[str, float]]) -> Path:
    path.write_text(json.dumps({"manoeuvres": manoeuvres}), encoding="utf-8")
    return path


def test_gap_command_passes_when_calibrated(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    sim = _write(tmp_path / "sim.json", SIM_METRICS)
    real = _write(tmp_path / "real.json", SIM_METRICS)  # identical: gap 0
    assert calibrate.main(["gap", "--sim", str(sim), "--real", str(real)]) == 0
    assert "gap = 0.0000  (good)" in capsys.readouterr().out


def test_gap_command_fails_above_the_ceiling(tmp_path: Path) -> None:
    """SPEC 11.3: above 0.20 evolution stops. Exit 1 is how the caller learns."""
    doubled = {m: {k: v * 2 for k, v in values.items()} for m, values in SIM_METRICS.items()}
    sim = _write(tmp_path / "sim.json", doubled)
    real = _write(tmp_path / "real.json", SIM_METRICS)
    assert calibrate.main(["gap", "--sim", str(sim), "--real", str(real)]) == 1


def test_fit_names_exactly_what_spec_8_3_must_gain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SPEC GAP: POST /v1/sim/run has no `physics` field, so `fit` cannot run.

    The refusal has to be actionable - endpoint, field, and all five SPEC 11.3
    parameter names - and it must not leave a physics file behind.
    """
    monkeypatch.setattr(calibrate.httpx, "Client", lambda **kw: _sim_brain([]))
    real = _write(tmp_path / "real.json", SIM_METRICS)
    out = tmp_path / "physics.json"

    with pytest.raises(SystemExit) as refused:
        calibrate.main(["fit", "--real", str(real), "--out", str(out)])

    message = str(refused.value)
    assert "/v1/sim/run" in message and "8.3" in message
    for parameter in calibrate.PhysicsParams.__dataclass_fields__:
        assert parameter in message
    assert not out.exists()


def _physics_brain(varies: bool) -> httpx.Client:
    """The brain as it will be once SPEC 8.3 gains the `physics` field.

    It echoes the block back, and with `varies` its metrics actually depend on the
    physics it was handed - the difference between a fit that can converge and one
    that cannot.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        physics = body.get("physics")
        metrics = dict(SIM_METRICS[body["skill_id"]])
        if varies and physics is not None:
            scale = physics["friction"] / calibrate.PhysicsParams().friction
            metrics = {k: v * scale for k, v in metrics.items()}
        return httpx.Response(201, json={"metrics": metrics, "physics": physics})

    return REAL_CLIENT(transport=httpx.MockTransport(handler), base_url="http://brain")


def test_fit_runs_once_the_endpoint_carries_the_physics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only sim_once() changes when SPEC 8.3 closes the gap; everything else works."""
    monkeypatch.setattr(calibrate.httpx, "Client", lambda **kw: _physics_brain(varies=True))
    target = 0.9 / calibrate.PhysicsParams().friction
    real = _write(
        tmp_path / "real.json",
        {m: {k: v * target for k, v in values.items()} for m, values in SIM_METRICS.items()},
    )
    out = tmp_path / "physics.json"

    assert calibrate.main(["fit", "--real", str(real), "--out", str(out)]) == 0

    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["params"]["friction"] == pytest.approx(0.9, abs=1e-4)
    assert written["residual"] < written["start_residual"]
    assert written["gap"] < 1e-6


def test_fit_is_refused_when_the_residual_does_not_improve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A simulator the parameters do not move cannot be calibrated: no fit is written."""
    monkeypatch.setattr(calibrate.httpx, "Client", lambda **kw: _physics_brain(varies=False))
    real = _write(
        tmp_path / "real.json",
        {m: {k: v * 1.3 for k, v in values.items()} for m, values in SIM_METRICS.items()},
    )
    out = tmp_path / "physics.json"

    assert calibrate.main(["fit", "--real", str(real), "--out", str(out)]) == 1
    assert not out.exists()
