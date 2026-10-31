# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SPEC 14.4 budget: six resources, five daily plus monthly pcb_orders, reset 00:00 TRT.

The counters live in the `budget_usage` table (ADR-011), not in this process. T-084
wants 72 uninterrupted hours with no overrun, and an in-process counter refunds the
whole window every time the service restarts.

The zone is encoded, not the offset. Turkey sits at UTC+3 all year today, but a
hardcoded +03:00 would be a silent bug the day that changes.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from neml_brain.api.metrics import BUDGET_USED_RATIO  # SPEC 18.3, declared once
from neml_brain.db import repo
from neml_brain.db.session import get_sessionmaker
from neml_brain.paths import CONFIG_DIR

DEFAULT_CONFIG_PATH = CONFIG_DIR / "budget.yaml"

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


@dataclass(frozen=True, slots=True)
class Limit:
    resource: str
    limit: float
    unit: str
    period: str  # day | month (SPEC 14.4: pcb_orders is the only monthly one)
    on_exceed: str


class BudgetExceeded(RuntimeError):
    def __init__(self, limit: Limit, used: float, requested: float, resets_at: datetime) -> None:
        self.resource = limit.resource
        self.limit = limit.limit
        self.unit = limit.unit
        self.on_exceed = limit.on_exceed
        self.used = used
        self.requested = requested
        self.resets_at = resets_at
        super().__init__(
            f"{limit.resource} budget exhausted: {used}+{requested} > {limit.limit}"
            f" {limit.unit}, resets at {resets_at.isoformat()}"
        )


class Budget:
    """SPEC 14.4 limits over the persisted budget_usage counters (ADR-011).

    Reset is implicit: a new window is a new row, so there is nothing to zero and no
    reset job to run.
    """

    def __init__(
        self,
        config_path: Path = DEFAULT_CONFIG_PATH,
        *,
        sessions: SessionFactory | None = None,
        notify: Callable[[str, float], None] | None = None,
    ) -> None:
        raw: Mapping[str, Any] = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        hour, minute = (int(p) for p in str(raw.get("reset_at", "00:00")).split(":"))
        self._reset_time = time(hour, minute)
        self._zone = ZoneInfo(str(raw.get("timezone", "Europe/Istanbul")))
        self._notify_at_ratio = float(raw.get("notify_at_ratio", 0.90))
        self._limits = {
            name: Limit(
                resource=name,
                limit=float(cfg["limit"]),
                unit=str(cfg["unit"]),
                period=str(cfg.get("period", "day")),
                on_exceed=str(cfg["on_exceed"]),
            )
            for name, cfg in (raw.get("limits") or {}).items()
        }
        self._sessions = sessions
        self._notify = notify
        # ponytail: "one notice per window" is remembered in this process, so a restart can
        # repeat a single 90 % notification. Upgrade path: a flag column on budget_usage.
        self._notified: dict[str, date] = {}

    @property
    def limits(self) -> Mapping[str, Limit]:
        return self._limits

    def now(self) -> datetime:
        return datetime.now(self._zone)

    def window_start(self, period: str, now: datetime) -> datetime:
        local = now.astimezone(self._zone)
        start = datetime.combine(local.date(), self._reset_time, tzinfo=self._zone)
        if local < start:
            start -= timedelta(days=1)
        if period == "month":
            start = start.replace(day=1)
            if local < start:
                start = (start - timedelta(days=1)).replace(day=1)
        return start

    def period_key(self, resource: str, now: datetime | None = None) -> date:
        """This resource's `budget_usage.day`: the first day of its window (ADR-011)."""
        return self.window_start(self._limit(resource).period, now or self.now()).date()

    def resets_at(self, resource: str, now: datetime | None = None) -> datetime:
        limit = self._limit(resource)
        start = self.window_start(limit.period, now or self.now())
        if limit.period == "month":
            return (start + timedelta(days=32)).replace(day=1)
        return start + timedelta(days=1)

    async def used(self, resource: str, now: datetime | None = None) -> float:
        key = self.period_key(resource, now)
        async with self._session() as session:
            spent = await repo.budget_spent(session, day=key)
        return float(spent.get(resource, 0))

    async def ratio(self, resource: str, now: datetime | None = None) -> float:
        return await self.used(resource, now) / self._limit(resource).limit

    async def consume(self, resource: str, amount: float, now: datetime | None = None) -> float:
        """Charge the budget or refuse. Returns the new used ratio.

        Check and charge are one statement (ADR-011): reading the total and then writing it
        back lets two concurrent consumers observe the same total and both pass the same
        limit check. The upsert charges first, so an over-limit consume rolls back -- which
        is also what holds the row lock until the charge is gone.
        """
        limit = self._limit(resource)
        moment = now or self.now()
        key = self.period_key(resource, moment)
        charge = Decimal(str(amount))
        async with self._session() as session:
            used = await repo.consume_budget(session, resource=resource, amount=charge, day=key)
            if used > Decimal(str(limit.limit)):
                await session.rollback()
                raise BudgetExceeded(
                    limit, float(used - charge), amount, self.resets_at(resource, moment)
                )
            await session.commit()
        ratio = float(used) / limit.limit
        BUDGET_USED_RATIO.labels(resource).set(ratio)
        if ratio >= self._notify_at_ratio and self._notified.get(resource) != key:
            self._notified[resource] = key
            if self._notify is not None:
                self._notify(resource, ratio)  # SPEC 14.4: a notification goes out at 90 %
        return ratio

    async def snapshot(self, now: datetime | None = None) -> dict[str, dict[str, Any]]:
        """Feeds /v1/budget and the mobile bars (SPEC 14.4)."""
        moment = now or self.now()
        keys = {name: self.period_key(name, moment) for name in self._limits}
        async with self._session() as session:
            spent = {key: await repo.budget_spent(session, day=key) for key in set(keys.values())}
        out: dict[str, dict[str, Any]] = {}
        for name, limit in self._limits.items():
            used = float(spent[keys[name]].get(name, 0))
            ratio = used / limit.limit
            BUDGET_USED_RATIO.labels(name).set(ratio)
            out[name] = {
                "used": used,
                "limit": limit.limit,
                "unit": limit.unit,
                "ratio": ratio,
                "resets_at": self.resets_at(name, moment).isoformat(),
                "on_exceed": limit.on_exceed,
            }
        return out

    def _limit(self, resource: str) -> Limit:
        try:
            return self._limits[resource]
        except KeyError:
            raise KeyError(f"unknown budget resource {resource!r}") from None

    def _session(self) -> AbstractAsyncContextManager[AsyncSession]:
        """SPEC 17.3 NEML_DB_URL, read on first use so constructing a Budget needs no DB."""
        if self._sessions is None:
            self._sessions = get_sessionmaker()
        return self._sessions()
