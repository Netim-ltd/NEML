# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""RFC 7807 `application/problem+json` for every error (SPEC 8.3).

One place builds the body. Routers raise `Problem`; they never hand-roll an
error dict, so the shape cannot drift between endpoints.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any, cast

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

CONTENT_TYPE = "application/problem+json"


class Problem(Exception):
    """An error that is already an RFC 7807 problem."""

    def __init__(
        self,
        status: int,
        title: str,
        detail: str | None = None,
        type_: str = "about:blank",
        **members: Any,
    ) -> None:
        super().__init__(detail or title)
        self.status = status
        self.title = title
        self.detail = detail
        self.type = type_
        self.members = members


def problem_response(
    request: Request,
    status: int,
    title: str,
    detail: str | None = None,
    type_: str = "about:blank",
    **members: Any,
) -> JSONResponse:
    from neml_brain.logging import current_correlation_id

    body: dict[str, Any] = {
        "type": type_,
        "title": title,
        "status": status,
        "instance": request.url.path,
    }
    if detail is not None:
        body["detail"] = detail
    correlation_id = current_correlation_id()
    if correlation_id is not None:
        body["correlation_id"] = correlation_id
    body.update(members)
    return JSONResponse(status_code=status, content=jsonable_encoder(body), media_type=CONTENT_TYPE)


def install_error_handlers(app: FastAPI) -> None:
    async def on_problem(request: Request, exc: Exception) -> Response:
        problem = cast(Problem, exc)
        return problem_response(
            request, problem.status, problem.title, problem.detail, problem.type, **problem.members
        )

    async def on_http_exception(request: Request, exc: Exception) -> Response:
        http_exc = cast(StarletteHTTPException, exc)
        title = HTTPStatus(http_exc.status_code).phrase
        raw = http_exc.detail
        detail = raw if isinstance(raw, str) and raw != title else None
        return problem_response(request, http_exc.status_code, title, detail)

    async def on_validation_error(request: Request, exc: Exception) -> Response:
        return problem_response(
            request,
            422,
            "Unprocessable Entity",
            "Request body or parameters failed validation.",
            errors=cast(RequestValidationError, exc).errors(),
        )

    async def on_unhandled(request: Request, exc: Exception) -> Response:
        # No detail: an unhandled exception message can carry a DSN or a path.
        from neml_brain.logging import get_logger

        get_logger(__name__).exception("unhandled_error", path=request.url.path)
        return problem_response(request, 500, "Internal Server Error")

    app.add_exception_handler(Problem, on_problem)
    app.add_exception_handler(StarletteHTTPException, on_http_exception)
    app.add_exception_handler(RequestValidationError, on_validation_error)
    app.add_exception_handler(Exception, on_unhandled)
