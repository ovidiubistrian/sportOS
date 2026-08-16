"""Giving a club an address, and telling the identity provider about it.

Two things have to happen together, and forgetting the second is invisible
until a supporter tries to sign in: the domain has to resolve to the club, and
it has to be a registered redirect on the supporter client. Miss the second and
the club's website has a sign-in button that ends on Keycloak's "Invalid
parameter: redirect_uri" page — which looks like the platform is broken, and is.

So they live in one function. Every path that gives a club a domain goes
through it: sign-up, the demo seed, and whatever custom-domain screen comes
later.
"""

from __future__ import annotations

import re
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.ids import new_id
from app.identity.keycloak import get_admin
from app.tenants.models import ClubDomain

log = structlog.get_logger(__name__)

_SAFE = re.compile(r"[^a-z0-9-]")


def hostname_for(slug: str) -> str:
    """`<slug>.<platform domain>` — the address a club gets at sign-up.

    A subdomain rather than a path, because the whole public site resolves by
    Host: a club on a path would need every cache key, cookie and redirect in
    the system to learn about a second dimension.
    """
    clean = _SAFE.sub("", slug.strip().lower()).strip("-")
    return f"{clean}.{settings.public_site_domain}"


async def attach(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    club_id: UUID,
    hostname: str,
    kind: str = "PRIMARY",
) -> ClubDomain | None:
    """Point a hostname at a club, and let supporters sign in on it.

    Returns `None` when the hostname already belongs to somebody — including
    to this club, since re-attaching is not an error worth raising over.

    A Keycloak failure is logged, not raised. The domain still works for
    reading the site, only sign-in is affected, and losing a whole sign-up
    because the identity provider hiccuped would be the worse outcome. The
    backfill script exists precisely to repair that afterwards.
    """
    taken = await session.scalar(select(ClubDomain).where(ClubDomain.hostname == hostname))
    if taken is not None:
        return None

    domain = ClubDomain(
        id=new_id(),
        tenant_id=tenant_id,
        club_id=club_id,
        hostname=hostname,
        kind=kind,
        verification_status="VERIFIED",
    )
    session.add(domain)
    await session.flush()

    try:
        await get_admin().allow_redirect(hostname)
    except Exception as exc:
        log.warning("domain_redirect_not_registered", hostname=hostname, error=str(exc))

    log.info("club_domain_attached", hostname=hostname, club_id=str(club_id))
    return domain
