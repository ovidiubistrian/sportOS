"""The single place domain errors become HTTP responses.

Nothing else in the codebase constructs an error body. Unmapped exceptions
become a generic INTERNAL_ERROR with a request id — the detail goes to the
logs, never to the client.

`response_for` is that mapping, and the exception handlers are thin wrappers
around it. It is a function rather than only a set of handlers because not
every failure happens where the handlers can see it: Starlette installs them
inside `ExceptionMiddleware`, so anything raised in a middleware — the unit of
work committing, for one — sails straight past to the bare `Exception` handler
and becomes an opaque 500. A constraint violation deserves its 409 wherever it
was raised.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.context import current_request_id
from app.core.errors import Conflict, DomainError

log = structlog.get_logger(__name__)


def _body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "details": details or {},
        "request_id": current_request_id(),
    }


def _domain_response(exc: DomainError) -> JSONResponse:
    headers = {}
    if exc.status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    return JSONResponse(
        status_code=exc.status,
        content=_body(exc.code, exc.message, exc.details),
        headers=headers,
    )


def _validation_response(exc: RequestValidationError) -> JSONResponse:
    fields = [
        {
            "field": ".".join(str(p) for p in error["loc"][1:]) or str(error["loc"][0]),
            "code": error["type"].upper(),
            "message": error["msg"],
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=_body(
            "VALIDATION_ERROR", "The submitted data is not valid.", {"fields": fields}
        ),
    )


def _integrity_response(exc: IntegrityError) -> JSONResponse:
    # A constraint fired that the service did not anticipate. The constraint
    # name is useful to us and meaningless (and leaky) to a client.
    diag = getattr(exc.orig, "diag", None)
    log.warning(
        "integrity_error",
        constraint=getattr(diag, "constraint_name", None),
        table=getattr(diag, "table_name", None),
        column=getattr(diag, "column_name", None),
        # The database's own message. It names the constraint even when the
        # structured fields are empty, which is the difference between a
        # diagnosable failure and a shrug in the log.
        detail=str(exc.orig).strip()[:300] if exc.orig else None,
    )
    conflict = Conflict()
    return JSONResponse(
        status_code=conflict.status,
        content=_body(conflict.code, conflict.message),
    )


def _http_response(exc: StarletteHTTPException) -> JSONResponse:
    codes = {
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        429: "RATE_LIMITED",
    }
    return JSONResponse(
        status_code=exc.status_code,
        content=_body(codes.get(exc.status_code, "HTTP_ERROR"), str(exc.detail)),
        headers=getattr(exc, "headers", None),
    )


def response_for(request: Request, exc: Exception, *, echo_cors: bool = False) -> JSONResponse:
    """The response this exception becomes, wherever it was raised.

    `echo_cors` only for the bare-`Exception` handler, which Starlette runs
    outside `CORSMiddleware` — see `_cors_headers`. A caller that returns this
    response from inside the middleware stack must leave it off, or the headers
    would be set twice.
    """
    if isinstance(exc, DomainError):
        return _domain_response(exc)
    if isinstance(exc, RequestValidationError):
        return _validation_response(exc)
    if isinstance(exc, IntegrityError):
        return _integrity_response(exc)
    if isinstance(exc, StarletteHTTPException):
        return _http_response(exc)

    log.exception("unhandled_exception", path=request.url.path, method=request.method)
    message = (
        f"{type(exc).__name__}: {exc}"
        if not settings.is_production
        else "Something went wrong."
    )
    return JSONResponse(
        status_code=500,
        content=_body("INTERNAL_ERROR", message),
        headers=_cors_headers(request) if echo_cors else None,
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain(_: Request, exc: DomainError) -> JSONResponse:
        return _domain_response(exc)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _validation_response(exc)

    @app.exception_handler(IntegrityError)
    async def _integrity(_: Request, exc: IntegrityError) -> JSONResponse:
        return _integrity_response(exc)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _http_response(exc)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        return response_for(request, exc, echo_cors=True)


def _cors_headers(request: Request) -> dict[str, str]:
    """The CORS headers this response would have had, if anything had added them.

    A handler registered for bare `Exception` is not installed alongside the
    others: Starlette hands it to `ServerErrorMiddleware`, which wraps the
    entire application — CORSMiddleware included. So a 500 leaves without the
    headers every other response carries, and the browser reports "blocked by
    CORS policy: no Access-Control-Allow-Origin" instead of "500".

    That is a bad trade. The CORS message points at configuration, the real
    fault is in a request handler, and the two live in different files. Echoing
    the headers here costs nothing and lets the browser say what happened.

    Only for origins already on the allow-list — this reports the decision the
    middleware would have made, it does not make a new one.
    """
    origin = request.headers.get("origin")
    if not origin or origin not in settings.cors_origins:
        return {}
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
        "Vary": "Origin",
    }
