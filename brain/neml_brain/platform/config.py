# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Validated runtime policy for the hierarchical platform."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from neml_brain.platform.learning import AcceptanceThresholds, ModelBudgetTier


@dataclass(frozen=True)
class PlatformConfig:
    thresholds: AcceptanceThresholds
    tiers: tuple[ModelBudgetTier, ...]
    max_first_prototype_usd: float
    domains: dict[str, dict[str, Any]]


def load_config(path: Path) -> PlatformConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("platform config must be a mapping")
    acceptance = raw["model_acceptance"]
    thresholds = AcceptanceThresholds(
        min_sim_success=float(acceptance["min_sim_success"]),
        min_regression_success=float(acceptance["min_regression_success"]),
        max_reality_gap=float(acceptance["max_reality_gap"]),
        max_canary_failure=float(acceptance["max_canary_failure"]),
    )
    values = (
        thresholds.min_sim_success,
        thresholds.min_regression_success,
        thresholds.max_reality_gap,
        thresholds.max_canary_failure,
    )
    if any(not 0 <= value <= 1 for value in values):
        raise ValueError("model thresholds must be between 0 and 1")
    tiers = tuple(
        ModelBudgetTier(
            str(item["name"]), int(item["max_model_mb"]), int(item["min_validated_missions"])
        )
        for item in raw["model_budget_tiers"]
    )
    if not tiers or tiers[0].min_validated_missions != 0:
        raise ValueError("initial model budget tier required")
    if any(t.max_model_mb < 1 or t.min_validated_missions < 0 for t in tiers):
        raise ValueError("invalid model budget tier")
    if any(
        b.min_validated_missions <= a.min_validated_missions or b.max_model_mb < a.max_model_mb
        for a, b in zip(tiers, tiers[1:], strict=False)
    ):
        raise ValueError("model budget tiers must increase with proven missions")
    cap = float(raw["first_prototype"]["max_parts_cost_usd_exclusive"])
    if cap <= 0:
        raise ValueError("prototype cap must be positive")
    domains = raw["domains"]
    if not isinstance(domains, dict) or not domains:
        raise ValueError("at least one domain required")
    if any(
        not options.get("require_human_model_deployment", False) for options in domains.values()
    ):
        raise ValueError("physical model deployment must require human approval")
    return PlatformConfig(thresholds, tiers, cap, domains)
