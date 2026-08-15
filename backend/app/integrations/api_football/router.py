"""Super-admin control over the league feed.

The key is not here and cannot be set here — same rule as the writing
assistant. What a super admin controls is which of our competitions map to
which of the provider's, and when a season is pulled. The mapping is the part
that needs a human: only somebody who knows both catalogues can say that our
`liga-2` is their league 284.

Clubs get the result automatically. There is no per-club setup and no per-club
key: a club that has entered Liga 2 sees its fixtures appear once the platform
has linked that season.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import Requires
from app.audit.service import AuditService
from app.authz.scope import ScopeLevel
from app.competitions.models import Competition, CompetitionSeason
from app.core.context import RequestContext
from app.core.db import platform_session
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.ids import new_id
from app.integrations.api_football import sync as syncer
from app.integrations.api_football.client import (
    PROVIDER,
    ApiFootball,
    ProviderNotConfigured,
    ProviderUnavailable,
)
from app.integrations.models import ProviderLink, SyncRun

router = APIRouter(prefix="/platform/api-football", tags=["platform"])

READ = Requires("platform.tenant.read", scope_level=ScopeLevel.PLATFORM)
CURATE = Requires("platform.competition.manage", scope_level=ScopeLevel.PLATFORM)


class FeedStatus(BaseModel):
    # The key itself is never returned, only whether there is one.
    key_configured: bool
    base_url: str
    linked_seasons: int
    requests_today: int
    last_run_at: datetime | None
    last_error: str | None


class LinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competition_season_id: UUID
    provider_league_id: str = Field(min_length=1, max_length=32)
    provider_season: int = Field(ge=1900, le=2100)


class LinkOut(BaseModel):
    competition_season_id: UUID
    competition: str
    season: str
    provider_league_id: str
    provider_season: int
    synced_at: datetime | None


class SyncOut(BaseModel):
    kind: str
    created: int
    updated: int
    requests: int
    remaining: int | None


def _payload(link: ProviderLink) -> dict:
    return link.snapshot or {}


@router.get("", response_model=FeedStatus, summary="Is the league feed working")
async def feed_status(ctx: Annotated[RequestContext, Depends(READ)]) -> FeedStatus:
    from app.core.config import settings

    since = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    async with platform_session(reason="read the league feed status") as session:
        links = list(
            await session.scalars(
                select(ProviderLink).where(
                    ProviderLink.provider == PROVIDER,
                    ProviderLink.entity_type == "COMPETITION_SEASON",
                )
            )
        )
        runs = list(
            await session.scalars(
                select(SyncRun)
                .where(SyncRun.provider == PROVIDER, SyncRun.started_at >= since)
                .order_by(SyncRun.started_at.desc())
            )
        )

    failed = next((r for r in runs if r.status == "FAILED"), None)
    return FeedStatus(
        key_configured=bool(settings.api_football_key.get_secret_value()),
        base_url=settings.api_football_base_url,
        linked_seasons=len(links),
        requests_today=sum(run.requests for run in runs),
        last_run_at=runs[0].started_at if runs else None,
        last_error=failed.error if failed else None,
    )


@router.get("/links", response_model=list[LinkOut], summary="Linked seasons")
async def list_links(ctx: Annotated[RequestContext, Depends(READ)]) -> list[LinkOut]:
    async with platform_session(reason="list linked seasons") as session:
        links = list(
            await session.scalars(
                select(ProviderLink).where(
                    ProviderLink.provider == PROVIDER,
                    ProviderLink.entity_type == "COMPETITION_SEASON",
                )
            )
        )
        out: list[LinkOut] = []
        for link in links:
            season = await session.get(CompetitionSeason, link.local_id)
            if season is None:
                continue
            competition = await session.get(Competition, season.competition_id)
            payload = _payload(link)
            out.append(
                LinkOut(
                    competition_season_id=season.id,
                    competition=competition.name if competition else "—",
                    season=season.name,
                    provider_league_id=link.provider_id.split(":")[0],
                    provider_season=int(payload.get("season") or 0),
                    synced_at=link.synced_at,
                )
            )
        return out


@router.post(
    "/links",
    response_model=LinkOut,
    status_code=status.HTTP_201_CREATED,
    summary="Point one of our seasons at one of theirs",
)
async def create_link(
    payload: LinkIn,
    ctx: Annotated[RequestContext, Depends(CURATE)],
) -> LinkOut:
    """Linking hands the season's fixtures to the provider.

    From here the club can no longer edit those matches: sync writes them, and
    an edit would survive until the next pull. Anything the provider does not
    cover — friendlies, youth fixtures — the club still enters itself.
    """
    # The provider identifies a season by league *and* year, so the link's key
    # has to carry both or two seasons of one league collide.
    provider_key = f"{payload.provider_league_id}:{payload.provider_season}"

    async with platform_session(
        reason=f"link season {payload.competition_season_id} to API-Football"
    ) as session:
        season = await session.get(CompetitionSeason, payload.competition_season_id)
        if season is None:
            raise NotFound(
                object_type="competition_season",
                object_id=str(payload.competition_season_id),
            )

        clash = await session.scalar(
            select(ProviderLink).where(
                ProviderLink.provider == PROVIDER,
                ProviderLink.entity_type == "COMPETITION_SEASON",
                ProviderLink.provider_id == provider_key,
                ProviderLink.local_id != season.id,
            )
        )
        if clash is not None:
            raise Conflict("That provider season is already linked to another season.")

        link = await session.scalar(
            select(ProviderLink).where(
                ProviderLink.provider == PROVIDER,
                ProviderLink.entity_type == "COMPETITION_SEASON",
                ProviderLink.local_id == season.id,
            )
        )
        if link is None:
            link = ProviderLink(
                id=new_id(),
                provider=PROVIDER,
                entity_type="COMPETITION_SEASON",
                local_id=season.id,
                provider_id=provider_key,
            )
            session.add(link)
        link.provider_id = provider_key
        link.snapshot = {
            "league": payload.provider_league_id,
            "season": payload.provider_season,
        }

        competition = await session.get(Competition, season.competition_id)
        AuditService(session).record(
            ctx,
            action="platform.feed.link",
            object_type="competition_season",
            object_id=season.id,
            after={"provider": PROVIDER, "provider_id": provider_key},
        )
        await session.flush()

        return LinkOut(
            competition_season_id=season.id,
            competition=competition.name if competition else "—",
            season=season.name,
            provider_league_id=payload.provider_league_id,
            provider_season=payload.provider_season,
            synced_at=link.synced_at,
        )


@router.delete(
    "/links/{competition_season_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Stop syncing a season",
)
async def delete_link(
    competition_season_id: UUID,
    ctx: Annotated[RequestContext, Depends(CURATE)],
) -> None:
    """Unlinking hands the fixtures back to the clubs.

    The matches stay — they are real, and a league table depends on them — but
    their source becomes CLUB again, so a club can correct one. Nothing is
    deleted: a season of results is not the platform's to throw away.
    """
    from app.competitions.models import Match

    async with platform_session(
        reason=f"unlink season {competition_season_id} from API-Football"
    ) as session:
        link = await session.scalar(
            select(ProviderLink).where(
                ProviderLink.provider == PROVIDER,
                ProviderLink.entity_type == "COMPETITION_SEASON",
                ProviderLink.local_id == competition_season_id,
            )
        )
        if link is None:
            raise NotFound(object_type="provider_link")

        for match in await session.scalars(
            select(Match).where(Match.competition_season_id == competition_season_id)
        ):
            match.source = "CLUB"

        await session.delete(link)
        AuditService(session).record(
            ctx,
            action="platform.feed.unlink",
            object_type="competition_season",
            object_id=competition_season_id,
        )
        await session.flush()


@router.post(
    "/links/{competition_season_id}/sync",
    response_model=SyncOut,
    summary="Pull a season now",
)
async def sync_now(
    competition_season_id: UUID,
    ctx: Annotated[RequestContext, Depends(CURATE)],
    kind: Annotated[str, Query(pattern="^(FIXTURES|LIVE)$")] = "FIXTURES",
) -> SyncOut:
    """Run a pull by hand.

    The scheduled job does this nightly; this is for setting a season up and
    for the Saturday somebody wants the table right now. Every run is recorded
    with what it cost, because the allowance is shared across every club.
    """
    async with platform_session(reason=f"sync season {competition_season_id}") as session:
        link = await session.scalar(
            select(ProviderLink).where(
                ProviderLink.provider == PROVIDER,
                ProviderLink.entity_type == "COMPETITION_SEASON",
                ProviderLink.local_id == competition_season_id,
            )
        )
        if link is None:
            raise ValidationFailed(
                "This season is not linked to API-Football yet.",
                field="competition_season_id",
            )
        season = await session.get(CompetitionSeason, competition_season_id)
        if season is None:
            raise NotFound(object_type="competition_season")

        run = SyncRun(
            id=new_id(),
            provider=PROVIDER,
            kind=kind,
            competition_season_id=season.id,
            started_at=datetime.now(UTC),
            status="RUNNING",
        )
        session.add(run)
        await session.flush()

        payload = _payload(link)
        try:
            async with ApiFootball() as client:
                if kind == "LIVE":
                    result = await syncer.sync_live(session, client, season=season)
                else:
                    result = await syncer.sync_fixtures(
                        session,
                        client,
                        season=season,
                        provider_league=str(payload.get("league")),
                        provider_season=int(payload.get("season") or 0),
                    )
        except ProviderNotConfigured as exc:
            run.status, run.error = "FAILED", str(exc)
            run.finished_at = datetime.now(UTC)
            await session.flush()
            raise ValidationFailed(str(exc), field="key_configured") from exc
        except ProviderUnavailable as exc:
            run.status, run.error = "FAILED", str(exc)[:500]
            run.finished_at = datetime.now(UTC)
            await session.flush()
            raise ValidationFailed(str(exc), field="provider") from exc

        run.status = "OK"
        run.finished_at = datetime.now(UTC)
        run.requests = result.requests
        run.created = result.created
        run.updated = result.updated
        link.synced_at = datetime.now(UTC)
        await session.flush()

        return SyncOut(
            kind=kind,
            created=result.created,
            updated=result.updated,
            requests=result.requests,
            remaining=result.remaining,
        )
