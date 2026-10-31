# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""structlog JSON logging with the audit correlation id (SPEC 8.1, 5.4, 18.3).

Every log line carries ``correlation_id``. The same id is bound for the whole
request, returned in the ``X-NEML-Correlation-Id`` header and written to
``audit_log`` alongside each tool call (SPEC 5.4), so a mobile approval, the
agent step it triggered and the MCP call it made share one key.

Output goes to stdout as one JSON object per line: journald picks it up,
Loki is optional (SPEC 18.3).
"""

from __future__ import annotations

import logging
import sys
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from starlette.requests import Request
from starlette.responses import Response

CORRELATION_HEADER = "X-NEML-Correlation-Id"


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON pipeline. Idempotent; call once at startup."""
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[level.upper()]
        ),
        logger_factory=structlog.WriteLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    return structlog.get_logger(name)


def bind_correlation_id(correlation_id: str | None = None) -> str:
    """Bind (or mint) the correlation id for the current async context."""
    correlation_id = correlation_id or uuid.uuid4().hex
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
    return correlation_id


def current_correlation_id() -> str | None:
    value = structlog.contextvars.get_contextvars().get("correlation_id")
    return value if isinstance(value, str) else None


async def correlation_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Accept an upstream correlation id (bridge, mobile) or mint one."""
    structlog.contextvars.clear_contextvars()
    correlation_id = bind_correlation_id(request.headers.get(CORRELATION_HEADER))
    response = await call_next(request)
    response.headers[CORRELATION_HEADER] = correlation_id
    return response
