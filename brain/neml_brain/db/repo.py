# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# The handful of queries the rest of neml-brain actually runs. No generic repository:
# every function here is named after the SPEC paragraph that needs it.

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from sqlalchemy.engine import CursorResult

from neml_brain.db.models import (
    Approval,
    BudgetUsage,
    PrintJob,
    SimRun,
    SkillRun,
    Task,
    TaskRun,
    Telemetry,
)

# SPEC 14.2: physical work happens in these task_runs environments.
PHYSICAL_ENVS = ("bench", "tethered", "free")


async def next_task(session: AsyncSession) -> Task | None:
    """SPEC 14.1 pick_next_task / SPEC 14.2: queue is ordered P DESC, ties by created_at ASC."""
    stmt = (
        sa.select(Task)
        .where(Task.state == "queued")
        .order_by(Task.priority.desc(), Task.created_at.asc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def pending_approvals(
    session: AsyncSession, *, now: dt.datetime | None = None
) -> Sequence[Approval]:
    """SPEC 8.3 GET /v1/approvals: undecided and not yet expired, oldest request first."""
    cutoff = now or dt.datetime.now(dt.UTC)
    stmt = (
        sa.select(Approval)
        .where(Approval.decision.is_(None), Approval.expires_at > cutoff)
        .order_by(Approval.requested_at.asc())
    )
    return (await session.execute(stmt)).scalars().all()


async def expire_approvals(session: AsyncSession, *, now: dt.datetime | None = None) -> int:
    """Flip undecided approvals past expires_at to 'expired' (SPEC 7 decision enum)."""
    cutoff = now or dt.datetime.now(dt.UTC)
    stmt = (
        sa.update(Approval)
        .where(Approval.decision.is_(None), Approval.expires_at <= cutoff)
        .values(decision="expired", decided_at=cutoff, decided_by="system")
    )
    # An UPDATE always comes back as a CursorResult; Result[Any] is the declared type.
    result = cast("CursorResult[Any]", await session.execute(stmt))
    return result.rowcount


async def budget_usage(
    session: AsyncSession, *, day_start: dt.datetime, month_start: dt.datetime
) -> dict[str, float]:
    """SPEC 14.4 rollup *derived from the source tables*: what the lab actually recorded today.

    Not the budget counter -- that is `budget_spent()` over the `budget_usage` table (ADR-011),
    which is what a limit check reads. This one stays useful only for reconciling the charged
    total against the rows it was charged for; the two are allowed to differ, and a drift is a
    finding, not a fallback.
    ponytail: one round trip, scalar subqueries; split it if any of these tables ever needs
    its own time index.
    """
    sim_runs = sa.select(sa.func.count()).select_from(SimRun).where(SimRun.run_at >= day_start)
    elapsed = sa.func.coalesce(TaskRun.ended_at, sa.func.now()) - TaskRun.started_at
    robot_seconds = (
        sa.select(sa.func.coalesce(sa.func.sum(sa.func.extract("epoch", elapsed)), 0))
        .select_from(TaskRun)
        .where(TaskRun.env.in_(PHYSICAL_ENVS), TaskRun.started_at >= day_start)
    )
    filament = (
        sa.select(sa.func.coalesce(sa.func.sum(PrintJob.est_filament_g), 0))
        .select_from(PrintJob)
        .where(PrintJob.started_at >= day_start)
    )
    # SPEC 14.4: PCB orders are the one monthly budget.
    pcb = (
        sa.select(sa.func.count())
        .select_from(Approval)
        .where(
            Approval.subject_kind == "gerber",
            Approval.decision == "approved",
            Approval.decided_at >= month_start,
        )
    )
    row = (
        await session.execute(
            sa.select(
                sim_runs.scalar_subquery().label("sim_runs"),
                robot_seconds.scalar_subquery().label("robot_seconds"),
                filament.scalar_subquery().label("filament_grams"),
                pcb.scalar_subquery().label("pcb_orders"),
            )
        )
    ).one()
    return {
        "sim_runs": float(row.sim_runs),
        "robot_hours": float(row.robot_seconds) / 3600.0,
        "filament_grams": float(row.filament_grams),
        "pcb_orders": float(row.pcb_orders),
    }


async def skill_success_rate(
    session: AsyncSession, skill_id: str, *, window: int = 20
) -> float | None:
    """SPEC 14.6 step 4 / SPEC 14.2: rolling success over the last `window` runs of a skill.

    One `skill_runs` row is one trial (ADR-011), so "last 20 runs" is literal here.
    SPEC 11.2 rule 3: a run marked `deterministic=false` never feeds an evolution or repair
    decision, so it is excluded by the query itself -- no caller can forget it.

    Returns None when the skill has no usable runs; < 0.70 is what triggers a `repair` task.
    """
    recent = (
        sa.select(SkillRun.success)
        .where(SkillRun.skill_id == skill_id, SkillRun.deterministic.is_(True))
        .order_by(SkillRun.run_at.desc(), SkillRun.id.desc())
        .limit(window)
        .subquery()
    )
    stmt = sa.select(sa.func.avg(sa.case((recent.c.success, 1), else_=0)).cast(sa.Float))
    rate = (await session.execute(stmt)).scalar_one_or_none()
    return None if rate is None else float(rate)


async def consume_budget(
    session: AsyncSession, *, resource: str, amount: Decimal, day: dt.date
) -> Decimal:
    """SPEC 14.4 / T-084: charge `resource` and return its new total for `day`, atomically.

    One statement, so two concurrent consumers cannot both read the same total and both pass
    the same limit check. The caller compares the returned total against config/budget.yaml
    and, if it lands over the limit, refunds by consuming the negative amount.

    `resource` is one of config/budget.yaml's `limits` keys. Reset is implicit: a new day is
    a new row. `pcb_orders` is monthly (SPEC 14.4), so its caller passes the month's first day.
    """
    stmt = (
        pg_insert(BudgetUsage)
        .values(day=day, resource=resource, used=amount)
        .on_conflict_do_update(
            index_elements=[BudgetUsage.day, BudgetUsage.resource],
            set_={"used": BudgetUsage.used + amount},
        )
        .returning(BudgetUsage.used)
    )
    return (await session.execute(stmt)).scalar_one()


async def budget_spent(session: AsyncSession, *, day: dt.date) -> dict[str, Decimal]:
    """SPEC 14.4: every counter recorded under `day`. A resource with no row has spent nothing,
    so it is simply absent -- callers default it to 0.
    """
    stmt = sa.select(BudgetUsage.resource, BudgetUsage.used).where(BudgetUsage.day == day)
    return {row.resource: row.used for row in (await session.execute(stmt))}


async def telemetry_range(
    session: AsyncSession,
    *,
    robot_id: str,
    metric: str,
    start: dt.datetime,
    end: dt.datetime,
    limit: int = 10_000,
    after: dt.datetime | None = None,
) -> Sequence[Telemetry]:
    """SPEC 8.3 GET /v1/telemetry. Hits telemetry_robot_id_metric_ts_idx and prunes partitions.

    `after` is the keyset cursor: pass the last row's ts to get the next page.
    """
    stmt = sa.select(Telemetry).where(
        Telemetry.robot_id == robot_id,
        Telemetry.metric == metric,
        Telemetry.ts >= start,
        Telemetry.ts < end,
    )
    if after is not None:
        stmt = stmt.where(Telemetry.ts > after)
    stmt = stmt.order_by(Telemetry.ts.asc()).limit(limit)
    return (await session.execute(stmt)).scalars().all()
