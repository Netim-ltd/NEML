# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`python -m neml_brain.autonomy` - the SPEC 14.1 service (systemd / compose)."""

from __future__ import annotations

import asyncio
import signal

import structlog

from neml_brain.autonomy import service

log = structlog.get_logger("neml_brain.autonomy")


async def main() -> None:
    if not service.enabled():
        # Idle, not exit: a supervisor that restarts on exit would spin forever.
        log.warning("autonomy.disabled", hint="set NEML_AUTONOMY_ENABLED=true to start the loop")
        await asyncio.Event().wait()
    service.require_sim_only()

    from neml_brain.autonomy.wiring import build_service  # heavy imports stay lazy

    svc, aclose = await build_service()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    try:
        log.info("autonomy.started", mode="sim_only")
        await service.run(svc, stop)
    finally:
        await aclose()


if __name__ == "__main__":
    asyncio.run(main())
