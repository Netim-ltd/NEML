# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Capability gaps and bounded design requests; no purchase side effects."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from neml_brain.platform.core import Scope
from neml_brain.platform.robots import PluginRegistry


@dataclass(frozen=True)
class CapabilityGap:
    scope: Scope
    task_id: str
    required: frozenset[str]
    reason: str


def detect_gap(
    plugins: PluginRegistry, scope: Scope, task_id: str, required: frozenset[str]
) -> CapabilityGap | None:
    if plugins.capable(required):
        return None
    return CapabilityGap(scope, task_id, required, "no registered robot type has all capabilities")


@dataclass(frozen=True)
class BomLine:
    part: str
    quantity: int
    unit_usd: Decimal
    supplier_alternative: str

    def __post_init__(self) -> None:
        if self.quantity < 1 or self.unit_usd < 0 or not self.supplier_alternative:
            raise ValueError("invalid BOM line")


@dataclass(frozen=True)
class DesignPackage:
    gap: CapabilityGap
    requirements_path: str
    freecad_path: str
    kicad_path: str
    firmware_path: str
    simulation_report_path: str
    bom: tuple[BomLine, ...]
    estimated_shipping_tax_usd: Decimal | None = None
    version_commit: str | None = None

    @property
    def parts_cost_usd(self) -> Decimal:
        return sum((line.unit_usd * line.quantity for line in self.bom), Decimal(0))

    def affordable_first_prototype(self) -> bool:
        return bool(self.bom) and self.parts_cost_usd < Decimal("50.00")


class ApprovalVerifier(Protocol):
    def approved(self, approval_id: str, scope: Scope, subject_id: str) -> bool: ...


class PurchaseRequestSender(Protocol):
    def send(self, recipient: str, package: DesignPackage) -> str: ...


def request_parts(
    package: DesignPackage,
    *,
    recipient: str,
    allowed_recipients: frozenset[str],
    approval_id: str,
    verifier: ApprovalVerifier,
    sender: PurchaseRequestSender,
) -> str:
    if not package.affordable_first_prototype():
        raise PermissionError("first prototype parts cost must be below 50 USD")
    if recipient not in allowed_recipients:
        raise PermissionError("recipient is not allowlisted")
    if not verifier.approved(approval_id, package.gap.scope, package.gap.task_id):
        raise PermissionError("human approval required")
    return sender.send(recipient, package)
