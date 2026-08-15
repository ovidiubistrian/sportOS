"""Where a visit is recorded.

Unauthenticated and host-scoped like the rest of `/public`, and written to be
the cheapest endpoint in the application: a club's home page calls it on every
navigation, so it does one Redis round trip and one insert, and it never makes
the visitor wait for either.

It is also the endpoint most worth being careful with, because it takes input
from anybody. Nothing here is trusted: the path is truncated and stripped of
its query string, the referrer is reduced to a host, the kind must be one we
declared, and the address and agent are hashed rather than stored. There is
nothing an attacker can put in this table that a dashboard will render as
anything but text.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Header, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.analytics import geo, service
from app.analytics.models import EVENT_KINDS, AnalyticsEvent
from app.core.cache import cache
from app.core.db import tenant_session
from app.tenants.site_service import resolve_host

router = APIRouter(prefix="/public", tags=["public"])

# A generous ceiling per visitor per minute. High enough that a real person
# clicking quickly is never refused, low enough that one script cannot write a
# million rows into a club's table overnight.
MAX_EVENTS_PER_MINUTE = 120


class TrackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = "PAGEVIEW"
    path: str = Field(default="/", max_length=300)
    referrer: str | None = Field(default=None, max_length=800)
    utm_source: str | None = Field(default=None, max_length=80)
    utm_medium: str | None = Field(default=None, max_length=80)
    utm_campaign: str | None = Field(default=None, max_length=120)
    locale: str | None = Field(default=None, max_length=10)
    value_minor: int | None = Field(default=None, ge=0, le=100_000_000)


def _clean_path(raw: str) -> str:
    """A path without its query string.

    Query strings carry tokens, email addresses and unsubscribe ids. Keeping
    them would turn an analytics table into a place where secrets accumulate,
    and no club dashboard has ever needed one.
    """
    path = (raw or "/").split("?")[0].split("#")[0].strip()
    if not path.startswith("/"):
        path = "/" + path
    return path[:300]


@router.post(
    "/analytics/collect",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Record a visit",
    include_in_schema=False,
)
async def collect(
    payload: TrackIn,
    request: Request,
    response: Response,
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    x_forwarded_for: Annotated[str | None, Header(alias="X-Forwarded-For")] = None,
    user_agent: Annotated[str, Header(alias="User-Agent")] = "",
    host: Annotated[str | None, Header(alias="Host")] = None,
) -> None:
    response.headers["Cache-Control"] = "no-store"

    hostname = (x_forwarded_host or host or "").split(",")[0].strip()
    route = await resolve_host(hostname)
    # A beacon for an unknown domain is discarded silently. It is a
    # measurement, not a request anybody is waiting on, and a 404 here would
    # only tell a scanner which domains exist.
    if route is None:
        return

    if service.is_bot(user_agent):
        return

    kind = payload.kind if payload.kind in EVENT_KINDS else "PAGEVIEW"

    socket_ip = request.client.host if request.client else None
    address = service.client_ip(x_forwarded_for, socket_ip)
    visitor = await service.visitor_hash(
        ip=address, user_agent=user_agent, club_id=route.club_id
    )

    quota = f"analytics:rate:{visitor}"
    seen = await cache.incr(quota)
    if seen == 1:
        await cache.expire(quota, 60)
    if seen > MAX_EVENTS_PER_MINUTE:
        return

    session = await service.session_for(visitor)
    country, city = geo.locate(address)

    async with tenant_session(route.tenant_id) as db:
        db.add(
            AnalyticsEvent(
                tenant_id=route.tenant_id,
                club_id=route.club_id,
                occurred_at=datetime.now(UTC),
                kind=kind,
                visitor_hash=visitor,
                session_id=session,
                path=_clean_path(payload.path),
                referrer_host=service.referrer_host(payload.referrer, hostname),
                utm_source=payload.utm_source,
                utm_medium=payload.utm_medium,
                utm_campaign=payload.utm_campaign,
                # Resolved here and the address never stored — the row keeps a
                # place, not a person.
                country=country,
                city=city,
                device=service.device_of(user_agent),
                browser=service.browser_of(user_agent),
                locale=payload.locale,
                value_minor=payload.value_minor,
            )
        )
