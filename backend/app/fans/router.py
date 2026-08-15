"""Supporter-facing endpoints. Unauthenticated and host-scoped."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Header, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select

from app.core.cache import cache
from app.core.db import tenant_session
from app.core.errors import NotFound, RateLimited
from app.core.locales import normalise
from app.fans.models import NewsletterSubscriber
from app.tenants.models import Club
from app.tenants.site_service import resolve_host

router = APIRouter(prefix="/public", tags=["public"])

# A footer form on a public page is a spam target. Per address and per host,
# because the two abuses look different: one bot with one address hammering,
# and many addresses from one place.
SIGNUPS_PER_HOUR = 5


class SubscribeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    locale: str | None = Field(default=None, max_length=10)


class SubscribeOut(BaseModel):
    # Deliberately the same answer whether the address was already on the list
    # or has just been added: a form that says "you are already subscribed"
    # tells a stranger who reads the club's newsletter.
    subscribed: bool = True


def _host(forwarded: str | None, header_host: str | None) -> str | None:
    return (forwarded or header_host or "").split(",")[0].strip() or None


@router.post(
    "/newsletter",
    response_model=SubscribeOut,
    status_code=status.HTTP_201_CREATED,
    summary="Subscribe to the club's newsletter",
)
async def subscribe(
    payload: SubscribeIn,
    response: Response,
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    host: Annotated[str | None, Header(alias="Host")] = None,
) -> SubscribeOut:
    hostname = _host(x_forwarded_host, host)
    route = await resolve_host(hostname)
    if route is None:
        raise NotFound("No club is published on this domain.")
    response.headers["Cache-Control"] = "no-store"

    key = f"newsletter:{hostname}:{payload.email.lower()}"
    attempts = await cache.incr(key)
    if attempts == 1:
        await cache.expire(key, 3600)
    if attempts > SIGNUPS_PER_HOUR:
        raise RateLimited("Too many attempts. Try again later.")

    async with tenant_session(route.tenant_id) as session:
        club = await session.get(Club, route.club_id)
        existing = await session.scalar(
            select(NewsletterSubscriber).where(
                NewsletterSubscriber.club_id == route.club_id,
                NewsletterSubscriber.email == payload.email,
            )
        )
        if existing is not None:
            # Re-subscribing after unsubscribing is a fresh consent, and it
            # needs a fresh timestamp — the old one no longer describes it.
            existing.unsubscribed_at = None
            existing.consented_at = datetime.now(UTC)
        else:
            session.add(
                NewsletterSubscriber(
                    tenant_id=route.tenant_id,
                    club_id=route.club_id,
                    email=payload.email,
                    locale=normalise(payload.locale)
                    if payload.locale
                    else (club.default_locale if club else None),
                    consented_at=datetime.now(UTC),
                    source="SITE_FOOTER",
                )
            )

    return SubscribeOut()
