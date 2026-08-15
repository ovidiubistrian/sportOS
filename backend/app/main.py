from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.errors import register_exception_handlers
from app.api.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from app.api.router import api_v1
from app.core.cache import cache
from app.core.config import settings
from app.core.db import check_database, dispose_engines
from app.core.logging import configure_logging

# Import every module's models so they are registered on the declarative
# metadata before Alembic autogenerate or the isolation sweep runs.
from app.core import model_registry  # noqa: F401  isort: skip

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    log.info("api_starting", env=settings.app_env)

    if not settings.is_production:
        # Development convenience only. In production the bucket and its policy
        # are infrastructure — the runtime credentials there should not be able
        # to create buckets or set policies at all.
        from app.media.storage import ensure_bucket

        try:
            await ensure_bucket()
        except Exception as exc:
            log.warning("media_bucket_setup_failed", error=str(exc))

    yield
    await cache.close()
    await dispose_engines()
    log.info("api_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Football Club OS API",
        version="1.0.0",
        description=(
            "Multi-tenant API for club, academy, ticketing and fan operations. "
            "Every tenant-scoped endpoint resolves tenant context from the "
            "session — a tenant id is never accepted as input."
        ),
        openapi_url=f"{settings.api_prefix}/openapi.json",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        lifespan=lifespan,
    )

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Tenant-Id", "Idempotency-Key"],
        expose_headers=["X-Request-Id", "Idempotency-Replayed"],
        max_age=600,
    )

    register_exception_handlers(app)
    app.include_router(api_v1, prefix=settings.api_prefix)

    @app.get("/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        """Liveness: is the process up? Deliberately touches no dependency."""
        return {"status": "ok"}

    @app.get("/health/ready", include_in_schema=False)
    async def ready() -> JSONResponse:
        """Readiness: can this replica actually serve traffic?"""
        checks = {"database": await check_database(), "redis": await cache.ping()}
        healthy = all(checks.values())
        return JSONResponse(
            status_code=200 if healthy else 503,
            content={"status": "ok" if healthy else "degraded", "checks": checks},
        )

    return app


app = create_app()
