"""Handler wiring.

One import point for every subscriber, so the full set of side effects in the
system is readable in one file. Modules define their handlers; this file is
what makes them live.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from inspect import isawaitable
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.events.base import (
    ClubBrandingChanged,
    ContentPublished,
    DomainEvent,
    MatchScheduleChanged,
    PlayerRegistered,
    RoleAssigned,
    RoleRevoked,
)
from app.events.publisher import handler_transaction
from app.events.registry import handles

log = structlog.get_logger("events")


@handles(PlayerRegistered)
async def record_player_registration(event: PlayerRegistered) -> None:
    """Placeholder for the notification and analytics fan-out.

    Kept deliberately trivial for now: it exercises the claim/commit path end to
    end so the outbox is proven before anything depends on it.
    """
    async with handler_transaction("events.record_player_registration", event) as session:
        if session is None:
            return
        log.info(
            "player_registered_handled",
            player_id=str(event.aggregate_id),
            tenant_id=str(event.tenant_id),
        )


async def _invalidate_permissions(event: RoleAssigned | RoleRevoked) -> None:
    """Drop the caller's cached permissions the moment a grant changes.

    The Redis TTL is a safety net, not the mechanism: a revoked role must take
    effect on the next request, not within a minute.
    """
    from app.authz.service import PermissionResolver

    async with handler_transaction(
        f"events.invalidate_permissions.{event.event_type}", event
    ) as session:
        if session is None:
            return
        await PermissionResolver(session).invalidate(event.aggregate_id)
        log.info("permissions_invalidated", user_id=str(event.aggregate_id))


handles(RoleAssigned)(_invalidate_permissions)
handles(RoleRevoked)(_invalidate_permissions)


@handles(ClubBrandingChanged)
async def purge_public_site_cache(event: ClubBrandingChanged) -> None:
    """Drop the public site's cached configuration for this club's domains.

    Without it a club changes its colours and sees nothing for the length of the
    ISR window, which reads as the feature being broken. Routed through the
    outbox rather than called inline so a slow or down public-web cannot fail
    the club's save — the purge simply retries.
    """
    await _purge(event, reason="branding", resolve=lambda _: event.aggregate_id)


@handles(ClubBrandingChanged)
async def sync_directory_crest(event: ClubBrandingChanged) -> None:
    """Carry the club's crest across to its row in the shared directory.

    Two separate rows by design: `club` is the tenant's, `directory_club` is the
    platform's, and a fixture points at the second so two clubs in a division
    can render each other. But a club that uploads its badge expects to see it
    in its own fixture list and its own table, and nothing else was going to put
    it there.
    """
    from sqlalchemy import select

    from app.competitions.models import DirectoryClub
    from app.media import storage
    from app.media.models import MediaAsset
    from app.tenants.branding_models import ClubBranding
    from app.tenants.models import Club

    async with handler_transaction("events.sync_directory_crest", event) as session:
        if session is None:
            return

        club = await session.get(Club, event.aggregate_id)
        if club is None or club.directory_club_id is None:
            return

        directory = await session.get(DirectoryClub, club.directory_club_id)
        if directory is None:
            return

        branding = await session.scalar(
            select(ClubBranding).where(ClubBranding.club_id == club.id)
        )
        asset = (
            await session.get(MediaAsset, branding.crest_media_id)
            if branding and branding.crest_media_id
            else None
        )
        directory.crest_url = storage.public_url(asset.storage_key) if asset else None
        log.info("directory_crest_synced", club_id=str(club.id), has_crest=bool(asset))


@handles(MatchScheduleChanged)
async def purge_site_cache_for_matches(event: MatchScheduleChanged) -> None:
    """A fixture the club just entered has to be on the site now.

    The aggregate is the club, not the match: the site renders a whole fixture
    list and a whole table, so one recorded result invalidates both.
    """
    await _purge(event, reason="matches", resolve=lambda _: event.aggregate_id)


async def _purge(
    event: DomainEvent,
    *,
    reason: str,
    resolve: Callable[[AsyncSession], Awaitable[UUID | None] | UUID | None],
) -> None:
    """Drop the public site's cached pages for every domain of one club.

    Shared by the three things that change what a visitor sees — colours, a
    published article, a fixture. `resolve` finds the club from the event, in
    the same transaction that does the purge: splitting the two would mean a
    retry after a failed purge re-runs the resolve, is told the event is already
    handled, and quietly gives up on the purge it was retrying for.
    """
    import httpx
    from sqlalchemy import select

    from app.core.config import settings
    from app.tenants.models import ClubDomain

    async with handler_transaction("events.purge_public_site_cache", event) as session:
        if session is None:
            return

        club_id = resolve(session)
        if isawaitable(club_id):
            club_id = await club_id
        if club_id is None:
            return

        hostnames = list(
            await session.scalars(
                select(ClubDomain.hostname).where(ClubDomain.club_id == club_id)
            )
        )
        if not hostnames:
            return

        async with httpx.AsyncClient(timeout=5.0) as client:
            for hostname in hostnames:
                response = await client.post(
                    f"{settings.public_web_internal_url}/api/revalidate",
                    json={"host": hostname},
                    headers={
                        "X-Revalidate-Secret": settings.revalidate_secret.get_secret_value()
                    },
                )
                response.raise_for_status()
                log.info("public_site_cache_purged", host=hostname, reason=reason)


@handles(ContentPublished)
async def purge_site_cache_for_content(event: ContentPublished) -> None:
    """Make a published article appear immediately.

    Publishing is the one CMS action with an audience waiting for it — a club
    posting a team-news update expects it live now, not at the end of the ISR
    window.
    """
    from sqlalchemy import select

    from app.cms.models import ContentItem

    await _purge(
        event,
        reason="content",
        resolve=lambda session: session.scalar(
            select(ContentItem.club_id).where(ContentItem.id == event.aggregate_id)
        ),
    )
