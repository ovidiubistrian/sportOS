"""Public site resolution: hostname → club.

Runs for unauthenticated visitors, so there is no token and no tenant to start
from — the Host header is the only input. The lookup itself therefore needs a
cross-tenant read of `club_domain` (which is under RLS), done through a
platform-role session for exactly one indexed query on a unique column, and
cached. Everything after that runs on a normal tenant-bound session.

An unknown host is a 404. It never falls back to a default club: that would
serve one club's content on another club's domain, which is the single worst
failure this module could have.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import structlog
from sqlalchemy import select

from app.core.cache import cache
from app.core.db import platform_session
from app.tenants.models import ClubDomain

log = structlog.get_logger(__name__)

_CACHE_PREFIX = "site:host"
_CACHE_TTL = 300
# Cached separately and briefly, so a newly added domain starts working quickly
# but a hostile host cannot force a database query on every request.
_NEGATIVE_TTL = 30


@dataclass(frozen=True, slots=True)
class SiteRoute:
    tenant_id: UUID
    club_id: UUID


def normalise_host(host: str | None) -> str | None:
    """Lower-case, strip the port, drop a trailing dot."""
    if not host:
        return None
    value = host.strip().lower().rstrip(".")
    if not value:
        return None
    # IPv6 literals arrive bracketed; a club domain never does.
    if value.startswith("["):
        return None
    value = value.split(":", 1)[0]
    return value or None


async def resolve_host(host: str | None) -> SiteRoute | None:
    """Map a hostname to the club that owns it."""
    hostname = normalise_host(host)
    if hostname is None:
        return None

    key = f"{_CACHE_PREFIX}:{hostname}"
    cached = await cache.get_json(key)
    if cached is not None:
        if cached.get("miss"):
            return None
        return SiteRoute(UUID(cached["tenant_id"]), UUID(cached["club_id"]))

    async with platform_session(reason="resolve public hostname", routine=True) as session:
        row = await session.scalar(
            select(ClubDomain).where(
                ClubDomain.hostname == hostname,
                ClubDomain.verification_status == "VERIFIED",
            )
        )

    if row is None:
        await cache.set_json(key, {"miss": True}, ttl=_NEGATIVE_TTL)
        log.info("public_host_unknown", host=hostname)
        return None

    route = SiteRoute(row.tenant_id, row.club_id)
    await cache.set_json(
        key,
        {"tenant_id": str(route.tenant_id), "club_id": str(route.club_id)},
        ttl=_CACHE_TTL,
    )
    return route


async def invalidate_host(hostname: str) -> None:
    """Called whenever a club domain is added, verified or removed."""
    normalised = normalise_host(hostname)
    if normalised:
        await cache.delete(f"{_CACHE_PREFIX}:{normalised}")
