# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""print.cancel and print.qc: the two print-job commands the app can queue (SPEC 10.2 screen 11).

neml-mcp-fab is imported lazily and only here, so the brain still starts where the
repo-root `mcp_servers` package is absent. The wire shape of the QC form is the one
the mobile screen already sends (`dim_1_mm`, `mass_g`, ...).
"""

from __future__ import annotations

import dataclasses
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_ROW = sa.text("SELECT printer_id, state FROM print_jobs WHERE id = CAST(:id AS uuid)")
_END = sa.text(
    "UPDATE print_jobs SET state = 'cancelled', ended_at = now()"
    " WHERE id = CAST(:id AS uuid) AND state IN ('queued','printing')"
)


class FabRejected(Exception):
    pass


def qc_form(a: dict[str, Any], form_cls: Any) -> Any:
    """Mobile/cloud QC body -> the SPEC 12.5 form. Missing or non-numeric fields reject."""

    def num(key: str) -> float:
        v = a.get(key)
        if isinstance(v, bool) or not isinstance(v, int | float):
            raise FabRejected(f"{key} must be a number")
        return float(v)

    def flag(key: str) -> bool:
        v = a.get(key)
        if not isinstance(v, bool):
            raise FabRejected(f"{key} must be true or false")
        return v

    return form_cls(
        dim_nominal_mm=[num(f"dim_{i}_nominal_mm") for i in (1, 2, 3)],
        dim_measured_mm=[num(f"dim_{i}_mm") for i in (1, 2, 3)],
        hole_gauge_pass=flag("hole_gauge_ok"),
        mass_cad_g=num("mass_nominal_g"),
        mass_measured_g=num("mass_g"),
        layer_adhesion_pass=flag("layer_adhesion_ok"),
        warp_mm=num("warp_mm"),
    )


class FabOps:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @staticmethod
    def _fab() -> Any:
        try:
            from mcp_servers.neml_mcp_fab import qc, server
        except ImportError as exc:  # pragma: no cover - depends on the deployment image
            raise FabRejected("neml-mcp-fab is not installed in this process") from exc
        return server, qc

    async def cancel(self, print_job_id: str, reason: str | None) -> dict[str, Any]:
        async with self._sessions() as session:
            row = (await session.execute(_ROW, {"id": print_job_id})).first()
        if row is None:
            raise FabRejected(f"no print job {print_job_id}")
        if row.state not in ("queued", "printing"):
            raise FabRejected(f"print job is already {row.state}")
        if row.state == "printing":
            server, _ = self._fab()
            record = await server.reconcile(row.printer_id)
            if record is not None:  # nothing running means the printer already stopped
                await server.cancel(
                    server.JobHandle(
                        printer_id=record.printer_id,
                        job_id=record.job_id,
                        remote_path=record.remote_path,
                        approval_token=record.approval_token,
                    )
                )
        async with self._sessions() as session:
            await session.execute(_END, {"id": print_job_id})
            await session.commit()
        return {"printJobId": print_job_id, "state": "cancelled", "reason": reason}

    async def submit_qc(
        self, print_job_id: str, body: dict[str, Any], genome_id: str | None
    ) -> dict[str, Any]:
        server, qc = self._fab()
        try:
            report = await server.submit_qc(print_job_id, qc_form(body, qc.QcForm), genome_id or "")
        except (qc.QcError, server.FabError) as exc:
            raise FabRejected(str(exc)) from exc
        return dataclasses.asdict(report)
