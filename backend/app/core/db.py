"""Database engines and the tenant-scoped session.

Two engines, two roles:

  * `engine`          → app_runtime.  RLS applies. Used by every request.
  * `platform_engine` → app_platform. BYPASSRLS. Reachable only through
                        `platform_session()`, which is deliberately noisy.

Tenant context is applied per transaction with `set_config(..., is_local=true)`,
which is transaction-scoped and therefore safe behind a transaction-pooling
connection pooler. A plain `SET` would leak tenant context between pooled
clients, so it is never used.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.core.context import (
    current_tenant_id_optional,
    reset_platform_scope,
    reset_tenant_id,
    set_platform_scope,
    set_tenant_id,
)

log = structlog.get_logger(__name__)

_TENANT_SETTING = "app.tenant_id"
_USER_SETTING = "app.user_id"


def _create_engine(url: str) -> AsyncEngine:
    return create_async_engine(
        url,
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        # Behind PgBouncer in transaction mode, asyncpg's prepared-statement
        # cache must be disabled or connection reuse raises
        # "prepared statement already exists" under load.
        connect_args={"statement_cache_size": 0} if "asyncpg" in url else {},
    )


engine: AsyncEngine = _create_engine(settings.database_url)
platform_engine: AsyncEngine = _create_engine(settings.database_platform_url)

SessionFactory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)
PlatformSessionFactory = async_sessionmaker(
    platform_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)


async def _apply_tenant(session: AsyncSession, tenant_id: UUID | None) -> None:
    """Bind the RLS variable for the current transaction.

    When no tenant is set the variable is cleared, and the RLS policies
    evaluate `tenant_id = NULL` — which is never true. The failure mode of a
    missing tenant context is therefore an empty result set, not a data leak.
    """
    await session.execute(
        text("SELECT set_config(:key, :value, true)"),
        {"key": _TENANT_SETTING, "value": str(tenant_id) if tenant_id else ""},
    )


async def bind_tenant(session: AsyncSession, tenant_id: UUID | None) -> None:
    """Bind the tenant for the remainder of the current transaction.

    Used by session bootstrap, which starts with no tenant (it has to work out
    which tenants the caller may act in first) and then needs to read
    tenant-scoped configuration — subscriptions and entitlements — once the
    tenant is known.
    """
    await _apply_tenant(session, tenant_id)


async def bind_user(session: AsyncSession, user_id: UUID | None) -> None:
    """Bind the authenticated user for the current transaction.

    Read by the `tenant` table's RLS policy so session bootstrap can list the
    tenants this user belongs to without a BYPASSRLS connection. Transaction
    scoped, like the tenant setting, and for the same pooling reason.
    """
    await session.execute(
        text("SELECT set_config(:key, :value, true)"),
        {"key": _USER_SETTING, "value": str(user_id) if user_id else ""},
    )


@asynccontextmanager
async def tenant_session(
    tenant_id: UUID | None = None,
) -> AsyncIterator[AsyncSession]:
    """A unit of work bound to one tenant. Commits on success, rolls back on error."""
    resolved = tenant_id if tenant_id is not None else current_tenant_id_optional()
    async with SessionFactory() as session:
        await session.begin()
        await _apply_tenant(session, resolved)
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()


@asynccontextmanager
async def platform_session(
    *, reason: str, routine: bool = False
) -> AsyncIterator[AsyncSession]:
    """Cross-tenant access. Requires a stated reason and is always logged.

    Every use is visible in review and in the log stream. If this appears in a
    normal request path, that is a bug — the request should carry a tenant.

    `routine=True` marks the known infrastructure callers (the outbox relay,
    maintenance jobs, seeds) which legitimately run cross-tenant on a timer.
    They log at debug, so the warning keeps meaning "something unexpected
    reached across tenants" instead of scrolling past once a second.
    """
    if routine:
        log.debug("platform_scope_entered", reason=reason)
    else:
        log.warning("platform_scope_entered", reason=reason)
    scope_token = set_platform_scope(True)
    tenant_token = set_tenant_id(None)
    try:
        async with PlatformSessionFactory() as session:
            await session.begin()
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            else:
                await session.commit()
    finally:
        reset_platform_scope(scope_token)
        reset_tenant_id(tenant_token)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. Tenant comes from the request context, never a parameter."""
    async with tenant_session() as session:
        yield session


async def check_database() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # pragma: no cover - health path
        log.error("database_healthcheck_failed", error=str(exc))
        return False


async def dispose_engines() -> None:
    await engine.dispose()
    await platform_engine.dispose()
