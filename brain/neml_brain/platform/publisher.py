# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Move PostgreSQL outbox events into the existing durable outbound bridge."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import sqlalchemy as sa

from neml_brain.bridge.client import CloudBridge
from neml_brain.bridge.protocol import LabMessageType
from neml_brain.platform.core import Scope
from neml_brain.platform.store import PlatformStore


class PlatformPublisher:
    def __init__(self, store: PlatformStore, bridge: CloudBridge) -> None:
        self.store = store
        self.bridge = bridge

    async def drain_all(self) -> int:
        async with self.store._sessions() as session:
            tenants = cast(
                list[str],
                (
                    (await session.execute(sa.text("SELECT id FROM platform_tenants ORDER BY id")))
                    .scalars()
                    .all()
                ),
            )
        count = 0
        for tenant in tenants:
            async with self.store._scoped(Scope(tenant, "_index")) as session:
                domains = cast(
                    list[str],
                    (
                        (
                            await session.execute(
                                sa.text(
                                    "SELECT id FROM platform_domains WHERE tenant_id = :tenant"
                                ),
                                {"tenant": tenant},
                            )
                        )
                        .scalars()
                        .all()
                    ),
                )
            for domain in domains:
                scope = Scope(tenant, domain)
                for event in await self.store.pending_outbox(scope):
                    payload = event["payload"]
                    if payload.get("kind") == "ApprovalRequested":
                        message_type: LabMessageType = "approval_request"
                        body = payload["cloud_request"]
                    else:
                        message_type = "event"
                        body = payload
                    # send() commits to the SQLite outbox before this
                    # PostgreSQL row is marked delivered. A crash may resend
                    # with the same idempotency key; the cloud de-dupes it.
                    self.bridge.send(message_type, body, idempotency_key=event["event_id"])
                    await self.store.mark_delivered(scope, event["event_id"], datetime.now(UTC))
                    count += 1
        return count
