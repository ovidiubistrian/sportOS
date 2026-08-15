"""Leaving the list.

One endpoint, unauthenticated by necessity: somebody unsubscribing is holding
a link from an email, not a session. What makes that safe is the signature —
`hmac(secret, club + address)` — which cannot be guessed and cannot be reused
against another club.

`GET` and `POST` both work. The one-click unsubscribe every serious mailbox
provider offers sends a POST without asking the reader anything, and a link in
the body is a GET. Refusing either would mean somebody stays subscribed
because their mail client chose the other verb.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Header, Query, Response, status
from sqlalchemy import select

from app.core.db import tenant_session
from app.core.errors import NotFound
from app.fans.models import NewsletterSubscriber
from app.fans.supporter_models import Supporter
from app.marketing import service
from app.tenants.site_service import resolve_host

router = APIRouter(prefix="/public", tags=["public"])


async def _unsubscribe(hostname: str | None, email: str, token: str) -> None:
    route = await resolve_host(hostname)
    if route is None:
        raise NotFound("No club is published on this domain.")

    # A wrong signature is answered exactly like a right one. Telling somebody
    # their token was invalid would let an address be tested for membership.
    if not service.token_matches(route.club_id, email, token):
        return

    now = datetime.now(UTC)
    async with tenant_session(route.tenant_id) as db:
        subscriber = await db.scalar(
            select(NewsletterSubscriber).where(
                NewsletterSubscriber.club_id == route.club_id,
                NewsletterSubscriber.email == email,
            )
        )
        if subscriber is not None and subscriber.unsubscribed_at is None:
            subscriber.unsubscribed_at = now

        # A supporter who unsubscribes keeps their account and their order
        # history — they have withdrawn consent to be marketed at, which is not
        # the same as closing the account.
        supporter = await db.scalar(
            select(Supporter).where(
                Supporter.club_id == route.club_id, Supporter.email == email
            )
        )
        if supporter is not None:
            supporter.marketing_opt_in_at = None


@router.get(
    "/unsubscribe",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Leave the club's list",
    include_in_schema=False,
)
async def unsubscribe_get(
    response: Response,
    e: Annotated[str, Query(max_length=320)],
    t: Annotated[str, Query(max_length=64)],
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    host: Annotated[str | None, Header(alias="Host")] = None,
) -> None:
    response.headers["Cache-Control"] = "no-store"
    await _unsubscribe((x_forwarded_host or host or "").split(",")[0].strip(), e.lower(), t)


@router.post(
    "/unsubscribe",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="One-click unsubscribe",
    include_in_schema=False,
)
async def unsubscribe_post(
    response: Response,
    e: Annotated[str, Query(max_length=320)],
    t: Annotated[str, Query(max_length=64)],
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    host: Annotated[str | None, Header(alias="Host")] = None,
) -> None:
    response.headers["Cache-Control"] = "no-store"
    await _unsubscribe((x_forwarded_host or host or "").split(",")[0].strip(), e.lower(), t)
