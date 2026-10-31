# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""FastAPI routers — one module per SPEC 8.3 resource group."""

from fastapi import APIRouter

from neml_brain.api import (
    approvals,
    budget,
    command,
    genomes,
    health,
    metrics,
    model_settings,
    platform,
    robots,
    runtime,
    sim,
    skills,
    tasks,
    telemetry,
)

ROUTERS: tuple[APIRouter, ...] = (
    health.router,
    robots.router,
    tasks.router,
    command.router,
    skills.router,
    genomes.router,
    approvals.router,
    telemetry.router,
    sim.router,
    budget.router,
    runtime.router,
    metrics.router,
    model_settings.router,
    platform.router,
)

__all__ = ["ROUTERS"]
