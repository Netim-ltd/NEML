# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 11.3 sim-to-real protocol driver (T-076, T-077).

Three thin commands over the brain API (:8080). The protocol itself - the five
reference manoeuvres, the gap formula, the action bands and the least_squares
fit - lives in brain/neml_brain/evolution/reality_gap.py and is imported, not
repeated here.

    python scripts/calibration/calibrate.py run  --side sim  --out sim.json
    python scripts/calibration/calibrate.py run  --side real --out real.json --robot quad-01
    python scripts/calibration/calibrate.py gap  --sim sim.json --real real.json
    python scripts/calibration/calibrate.py fit  --real real.json --out physics.json

Both sides go through one interface - measure_once() -> _measures() ->
aggregate() - so sim and reality come back under the same measure names, reduced
the same way. That is what makes the two files subtractable in the gap formula.

`gap` exits 1 when the gap is above 0.20: at that point SPEC 11.3 stops
evolution until the physics is recalibrated, and the exit code is how a cron job
or a CI step finds out. `fit` exits 1 when the fit is refused.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx
from neml_brain.evolution.reality_gap import (
    MANOEUVRES,
    MANOEUVRES_BY_ID,
    REPEATS,
    CalibrationRejectedError,
    PhysicsParams,
    band,
    calibrate,
    manoeuvre_gap,
    reality_gap,
)

BRAIN_URL = os.environ.get("NEML_BRAIN_URL", "http://localhost:8080")
CALIBRATION_WORLD = "flat"  # SPEC 11.1 - the reference manoeuvres run on flat
SEED_BASE = 11_030_000  # deterministic and traceable: SPEC 11.3, run index below
TERMINAL = {"succeeded", "failed", "cancelled"}


def seed_for(manoeuvre_index: int, repetition: int) -> int:
    """Same manoeuvre + same repetition -> same seed, every campaign (SPEC 11.2)."""
    return SEED_BASE + manoeuvre_index * 100 + repetition


# ------------------------------------------------------------------- the API


def _measures(manoeuvre_id: str, metrics: dict[str, Any], where: str) -> dict[str, float]:
    wanted = MANOEUVRES_BY_ID[manoeuvre_id].measures
    missing = [m for m in wanted if m not in metrics]
    if missing:
        raise SystemExit(f"{where}: {manoeuvre_id} did not report {missing}; got {sorted(metrics)}")
    return {m: float(metrics[m]) for m in wanted}


# SPEC GAP (SPEC 8.3 vs SPEC 11.3) - this is what blocks T-077's `fit`. Spelled
# out in full so closing it is a mechanical edit rather than a guess:
#
#   POST /v1/sim/run must gain ONE optional request field
#       "physics": {"friction", "joint_damping", "motor_gain",
#                   "body_inertia_correction", "comms_latency_s"}   (all floats)
#   - the five SPEC 11.3 calibration parameters; all five required when the object
#     is present, each validated against reality_gap.PARAM_BOUNDS;
#   - applied to the DART world for that one run: surface friction, joint damping,
#     actuator gain, base-link inertia scale, control-loop delay;
#   - echoed back unchanged as a top-level "physics" object in the response, so the
#     caller can prove the run used what it asked for;
#   - folded into sim_version (SPEC 11.2), because two runs with different physics
#     are not the same deterministic run.
#
# Until then `fit` must not run: least_squares would vary x while the simulator
# answered with the brain's own physics every iteration, and the "fitted"
# parameters would be noise dressed up as a calibration. sim_once() is the ONLY
# place in this file that speaks to the endpoint, so closing the gap means
# deleting the guard below and nothing else.
PHYSICS_FIELD_MISSING = (
    "POST /v1/sim/run did not echo back the `physics` block it was sent: SPEC 8.3 has "
    "no physics field yet, so this run used the brain's own physics and not the "
    "parameters the fit asked for. Every least_squares iteration would then simulate "
    "the same world and the fit would be noise. SPEC 8.3 must gain an optional request "
    "field `physics` carrying the five SPEC 11.3 parameters (friction, joint_damping, "
    "motor_gain, body_inertia_correction, comms_latency_s), apply them to that run, "
    "echo them back as a top-level `physics` object, and fold them into sim_version. "
    "`run` and `gap` (T-076) work today; only `fit` (T-077) is blocked."
)


def sim_once(
    client: httpx.Client,
    manoeuvre_id: str,
    seed: int,
    physics: PhysicsParams | None = None,
) -> dict[str, float]:
    body: dict[str, Any] = {
        "world_id": CALIBRATION_WORLD,
        "seed": seed,
        "profile": "fast",  # SPEC 4.5: no camera, CPU render, vLLM keeps the GPU
        "skill_id": manoeuvre_id,
        "duration_s": 60.0,
    }
    if physics is not None:
        body["physics"] = asdict(physics)
    response = client.post("/v1/sim/run", json=body)
    response.raise_for_status()
    result = response.json()
    if physics is not None and result.get("physics") != body["physics"]:
        raise SystemExit(PHYSICS_FIELD_MISSING)
    return _measures(manoeuvre_id, result.get("metrics", {}), "sim")


def real_once(
    client: httpx.Client, robot_id: str, manoeuvre_id: str, repetition: int, poll_s: float = 5.0
) -> dict[str, float]:
    """One manoeuvre on the real robot. The deployment gate of SPEC 5.2 applies:
    the task waits in `awaiting_approval` until a human approves it."""
    manoeuvre = MANOEUVRES_BY_ID[manoeuvre_id]
    created = client.post(
        "/v1/tasks",
        json={
            "title": f"{manoeuvre_id} calibration repetition {repetition + 1}/{REPEATS}",
            "kind": "calibration",
            "source": "script:calibration",
            "priority": 500,
            "robot_id": robot_id,
            "spec": {
                "manoeuvre": manoeuvre_id,
                "command": manoeuvre.command,
                "repetition": repetition,
                "measures": list(manoeuvre.measures),
            },
        },
    )
    created.raise_for_status()
    task_id = created.json()["id"]

    while True:
        task = client.get(f"/v1/tasks/{task_id}")
        task.raise_for_status()
        state = task.json()["state"]
        if state in TERMINAL:
            break
        time.sleep(poll_s)
    if state != "succeeded":
        raise SystemExit(f"task {task_id} ({manoeuvre_id} rep {repetition}) ended {state}")

    runs_response = client.get(f"/v1/tasks/{task_id}/runs")
    runs_response.raise_for_status()
    runs = runs_response.json()
    if not runs:
        raise SystemExit(f"task {task_id} succeeded with no run record")
    return _measures(manoeuvre_id, runs[-1].get("metrics", {}), "real")


# ----------------------------------------------------------------- commands


def aggregate(repetitions: list[dict[str, float]]) -> dict[str, float]:
    """One number per measure out of the ten repetitions.

    Median, not mean: a single bad repetition (a slipped foot, a tether snag) is
    exactly what ten repetitions exist to survive.
    """
    return {key: statistics.median(rep[key] for rep in repetitions) for key in repetitions[0]}


def measure_once(
    client: httpx.Client, side: str, robot_id: str | None, index: int, repetition: int
) -> dict[str, float]:
    """One repetition of one manoeuvre, whichever side it runs on.

    Sim and reality differ only behind this call: both return the same SPEC 11.3
    measure names, enforced by _measures(), which is what lets `gap` subtract one
    side's file from the other's.
    """
    manoeuvre_id = MANOEUVRES[index].id
    if side == "sim":
        return sim_once(client, manoeuvre_id, seed_for(index, repetition))
    return real_once(client, robot_id or "", manoeuvre_id, repetition)


def run_side(side: str, robot_id: str | None, base_url: str) -> dict[str, Any]:
    raw: dict[str, list[dict[str, float]]] = {}
    with httpx.Client(base_url=base_url, timeout=900.0) as client:
        for index, manoeuvre in enumerate(MANOEUVRES):
            raw[manoeuvre.id] = []
            for repetition in range(REPEATS):
                values = measure_once(client, side, robot_id, index, repetition)
                raw[manoeuvre.id].append(values)
                print(f"  {manoeuvre.id} {repetition + 1}/{REPEATS}: {values}")
    return {
        "side": side,
        "robot_id": robot_id,
        "world_id": CALIBRATION_WORLD if side == "sim" else None,
        "repetitions": raw,
        "manoeuvres": {mid: aggregate(reps) for mid, reps in raw.items()},
    }


def report_gap(sim: dict[str, Any], real: dict[str, Any]) -> float:
    for manoeuvre in MANOEUVRES:
        if manoeuvre.id in sim and manoeuvre.id in real:
            value = manoeuvre_gap(sim[manoeuvre.id], real[manoeuvre.id], manoeuvre.measures)
            print(f"  {manoeuvre.id}: {value:.4f}")
    gap = reality_gap(sim, real)
    print(f"gap = {gap:.4f}  ({band(gap)})")
    return gap


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brain", default=BRAIN_URL, help=f"brain API (default {BRAIN_URL})")
    sub = parser.add_subparsers(dest="command", required=True)

    run_cmd = sub.add_parser("run", help="five manoeuvres, ten repetitions each")
    run_cmd.add_argument("--side", choices=["sim", "real"], required=True)
    run_cmd.add_argument("--robot", help="robot id (required for --side real)")
    run_cmd.add_argument("--out", type=Path, required=True)

    gap_cmd = sub.add_parser("gap", help="reality gap between two measurement files")
    gap_cmd.add_argument("--sim", type=Path, required=True)
    gap_cmd.add_argument("--real", type=Path, required=True)

    fit_cmd = sub.add_parser("fit", help="least_squares physics fit against real data")
    fit_cmd.add_argument("--real", type=Path, required=True)
    fit_cmd.add_argument("--out", type=Path, required=True)
    fit_cmd.add_argument("--max-nfev", type=int, default=40, help="sim budget (default 40)")

    args = parser.parse_args(argv)

    if args.command == "run":
        if args.side == "real" and not args.robot:
            raise SystemExit("--robot is required for --side real")
        print(f"{len(MANOEUVRES)} manoeuvres x {REPEATS} repetitions on the {args.side} side")
        data = run_side(args.side, args.robot, args.brain)
        args.out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"{args.out}: written")
        return 0

    if args.command == "gap":
        sim = json.loads(args.sim.read_text(encoding="utf-8"))["manoeuvres"]
        real = json.loads(args.real.read_text(encoding="utf-8"))["manoeuvres"]
        gap = report_gap(sim, real)
        if band(gap) == "uncalibrated":
            print("evolution is stopped until the physics is recalibrated (SPEC 11.3)")
            return 1
        return 0

    real = json.loads(args.real.read_text(encoding="utf-8"))["manoeuvres"]
    with httpx.Client(base_url=args.brain, timeout=900.0) as client:

        def simulate(params: PhysicsParams) -> dict[str, dict[str, float]]:
            # One repetition per manoeuvre inside the fit: least_squares calls
            # this tens of times, and the ten-repetition average is what the
            # *real* side needed, not the simulator.
            return {
                m.id: sim_once(client, m.id, seed_for(i, 0), params)
                for i, m in enumerate(MANOEUVRES)
            }

        try:
            result = calibrate(real, simulate, max_nfev=args.max_nfev)
        except CalibrationRejectedError as refused:
            # The physics already installed is at least as good as the fit, so
            # applying it would make the simulator worse. Nothing is written.
            print(f"fit refused: {refused}")
            return 1
        except ValueError as bad:
            # A parameter outside its physical box (SPEC 11.3 PARAM_BOUNDS).
            print(f"fit refused: {bad}")
            return 1

    print(json.dumps(asdict(result.params), indent=2))
    print(
        f"residual {result.start_residual:.6g} -> {result.residual:.6g}, "
        f"gap after fit = {result.gap:.4f} ({band(result.gap)}), "
        f"converged={result.converged}, {result.evaluations} evaluations"
    )
    args.out.write_text(
        json.dumps(
            {
                "params": asdict(result.params),
                "gap": result.gap,
                "residual": result.residual,
                "start_residual": result.start_residual,
                "converged": result.converged,
                "evaluations": result.evaluations,
                "spec": "NEML_SPEC.md 11.3",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"{args.out}: written")
    return 0 if band(result.gap) != "uncalibrated" else 1


if __name__ == "__main__":
    sys.exit(main())
