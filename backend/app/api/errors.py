"""The single place domain errors become HTTP responses.

Nothing else in the codebase constructs an error body. Unmapped exceptions
become a generic INTERNAL_ERROR with a request id — the detail goes to the
logs, never to the client.
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


def _body(
    code: str, message: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "details": details or {},
        "request_id": current_request_id(),
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain(_: Request, exc: DomainError) -> JSONResponse:
        headers = {}
        if exc.status == 401:
            headers["WWW-Authenticate"] = "Bearer"
        return JSONResponse(
            status_code=exc.status,
            content=_body(exc.code, exc.message, exc.details),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
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

    @app.exception_handler(IntegrityError)
    async def _integrity(_: Request, exc: IntegrityError) -> JSONResponse:
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

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            429: "RATE_LIMITED",
        }
        return JSONResponse(
            status_code=exc.status_code,
            content=_body(
                codes.get(exc.status_code, "HTTP_ERROR"), str(exc.detail)
            ),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception(
            "unhandled_exception", path=request.url.path, method=request.method
        )
        message = (
            f"{type(exc).__name__}: {exc}"
            if not settings.is_production
            else "Something went wrong."
        )
        return JSONResponse(
            status_code=500, content=_body("INTERNAL_ERROR", message)
        )
