# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Prometheus registry and the ten mandatory metrics (SPEC 18.3).

All ten are declared at import time so ``/metrics`` exposes their HELP/TYPE
lines from the first scrape, before anything has happened. A dashboard panel
never shows "no data" because the process has not done that thing yet.

Other modules import these objects and set them; the API sets the three it
observes for free while serving a request.

ponytail: metrics the API does not observe (llm, gpu lock, sim, safety age)
are set by the module that owns the number. If a gauge ever goes stale
because nobody called that path, add one APScheduler refresh job -- do not
scrape services from the /metrics handler, that turns a scrape into an
outage when a component is down.
"""

from __future__ import annotations

from fastapi import APIRouter
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.responses import Response

LLM_REQUESTS = Counter(
    "neml_llm_requests_total",
    "LLM requests by prompt profile and outcome.",
    ["profile", "outcome"],
)
LLM_LATENCY = Histogram("neml_llm_latency_seconds", "LLM request latency in seconds.", ["profile"])
GPU_LOCK_WAIT = Histogram(
    "neml_gpu_lock_wait_seconds",
    "Time spent waiting for the GPU mutex (SPEC 4.5).",
    ["consumer"],
)
SIM_RUNS = Counter(
    "neml_sim_runs_total", "Simulation runs by profile and outcome.", ["profile", "outcome"]
)
TASK_QUEUE_DEPTH = Gauge("neml_task_queue_depth", "Tasks in a non-terminal state.")
BUDGET_USED_RATIO = Gauge(
    "neml_budget_used_ratio",
    "Used fraction of a daily budget (SPEC 14.4).",
    ["resource"],
)
BRIDGE_CONNECTED = Gauge("neml_bridge_connected", "1 when the cloud bridge WSS is up, else 0.")
ROBOT_BATTERY_SOC = Gauge(
    "neml_robot_battery_soc", "Robot battery state of charge, 0..1.", ["robot_id"]
)
APPROVAL_PENDING_COUNT = Gauge(
    "neml_approval_pending_count", "Approvals awaiting a human decision."
)
SAFETY_CHECK_AGE_HOURS = Gauge(
    "neml_safety_check_age_hours",
    "Hours since the last e-stop/watchdog check (SPEC 5.1).",
    ["robot_id"],
)

MANDATORY_METRICS = (
    "neml_llm_requests_total",
    "neml_llm_latency_seconds",
    "neml_gpu_lock_wait_seconds",
    "neml_sim_runs_total",
    "neml_task_queue_depth",
    "neml_budget_used_ratio",
    "neml_bridge_connected",
    "neml_robot_battery_soc",
    "neml_approval_pending_count",
    "neml_safety_check_age_hours",
)

router = APIRouter(tags=["metrics"])


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """SPEC 8.3 / 18.3 — Prometheus scrape endpoint."""
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
