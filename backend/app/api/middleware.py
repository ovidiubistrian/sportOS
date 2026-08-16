from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings
from app.core.context import set_request_id
from app.core.ids import new_id

log = structlog.get_logger("http")

Handler = Callable[[Request], Awaitable[Response]]


def enlist(request: Request, session: AsyncSession) -> None:
    """Hand a session to `UnitOfWorkMiddleware` to commit."""
    sessions: list[AsyncSession] | None = getattr(request.state, "sessions", None)
    if sessions is None:
        sessions = []
        request.state.sessions = sessions
    sessions.append(session)


class UnitOfWorkMiddleware(BaseHTTPMiddleware):
    """Commits the request's work before the response leaves the building.

    A dependency with `yield` runs its exit code *after* Starlette has handed
    the response to the client. Committing there means a caller can fail to
    read back its own write: `POST /products` returns 201, the row is committed
    a moment later, and a read that arrives in between finds nothing. The
    window is a millisecond on a warm machine, which is why it survived so
    long — the slower the commit, the wider it gets.

    Here `call_next` has returned, so the endpoint is finished and every
    dependency has done its work, but nothing has been sent yet. A client
    cannot observe the response before the commit because the commit happens
    first.

    Sessions still own rollback. An endpoint that raises unwinds through the
    dependency's exit code, so a failure is already discarded by the time it
    arrives here — and a route that *returns* a 4xx keeps whatever it wrote,
    committed by that same exit code as before. This middleware only moves the
    successful commit earlier; it never decides what persists.
    """

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        response = await call_next(request)
        if response.status_code < 400:
            for session in getattr(request.state, "sessions", ()):
                await session.commit()
        return response


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a correlation id and logs one structured line per request.

    The id is echoed in the response header and in every error body, so a user
    reporting "it failed" gives us something we can grep for directly.
    """

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        incoming = request.headers.get("x-request-id")
        request_id = incoming if incoming and len(incoming) <= 64 else str(new_id())
        token = set_request_id(request_id)

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception(
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            raise
        finally:
            from app.core.context import _request_id

            _request_id.reset(token)

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-Id"] = request_id
        if request.url.path not in ("/health", "/health/ready", "/metrics"):
            log.info(
                "request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=duration_ms,
            )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Defence-in-depth headers on API responses.

    The API returns JSON only, so the CSP is maximally restrictive: nothing
    should ever be loaded from an API response. The frontends set their own.
    """

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
        )
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        if settings.is_production:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
            )
        # Authenticated responses must never be cached by a shared cache.
        if not request.url.path.startswith(f"{settings.api_prefix}/public"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response
