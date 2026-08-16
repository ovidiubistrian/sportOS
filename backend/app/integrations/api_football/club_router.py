"""The league feed, from the club's side.

A club chooses one of two things: keep its calendar by hand, or point at its
team in the provider's catalogue and let the fixtures arrive. Both are real
answers — Liga IV and V are not in the provider's catalogue at all, so for
those clubs manual is not a fallback, it is the only option, and the interface
says so rather than offering a switch that quietly does nothing.

The key belongs to the platform, so every call a club causes spends a shared
allowance. That is why the intervals are settings with sane defaults rather
than a "refresh" button, and why the scheduler only polls live scores while a
match is actually being played.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from app.api.deps import Db, Requires
from app.audit.service import AuditService
from app.core.config import settings
from app.core.context import RequestContext
from app.core.errors import NotFound, ValidationFailed
from app.integrations.api_football import squads
from app.integrations.api_football.autolink import COUNTRY_NAMES
from app.integrations.api_football.client import (
    PROVIDER,
    ApiFootball,
    ProviderUnavailable,
)
from app.integrations.models import ClubFeed
from app.sports.registry import profile
from app.teams.models import Season, Team
from app.tenants.models import Club

router = APIRouter(tags=["competitions"])

READ = "teams.team.read"
MANAGE = "teams.team.manage"


class FeedSettings(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    club_id: UUID
    mode: str
    provider_team_id: str | None
    provider_team_name: str | None
    season_year: int | None
    sync_fixtures: bool
    sync_standings: bool
    sync_live: bool
    live_interval_minutes: int
    fixtures_interval_hours: int
    last_fixtures_at: datetime | None
    last_live_at: datetime | None
    last_error: str | None
    # Reported so the club is not offered a feed the platform cannot provide.
    provider_available: bool = True


class FeedUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str | None = None
    provider_team_id: str | None = Field(default=None, max_length=32)
    provider_team_name: str | None = Field(default=None, max_length=160)
    season_year: int | None = Field(default=None, ge=1900, le=2100)
    sync_fixtures: bool | None = None
    sync_standings: bool | None = None
    sync_live: bool | None = None
    live_interval_minutes: int | None = Field(default=None, ge=1, le=1440)
    fixtures_interval_hours: int | None = Field(default=None, ge=1, le=168)

    @field_validator("mode")
    @classmethod
    def _known_mode(cls, value: str | None) -> str | None:
        if value is not None and value not in ("MANUAL", "FEED"):
            raise ValueError("must be MANUAL or FEED")
        return value


class ProviderTeam(BaseModel):
    id: str
    name: str
    country: str | None
    logo: str | None
    founded: int | None


class ProviderLeague(BaseModel):
    """One division the provider covers, as a club would recognise it."""

    id: str
    name: str
    country: str | None
    logo: str | None
    tier: int | None = None
    season: int | None = None
    """The season the provider currently holds for it — what to ask for next."""


class ProviderCatalogue(BaseModel):
    """What the provider knows, and whether it knows anything at all.

    `available` is false for the two cases a club must be able to tell apart
    without reading an error: the platform has no provider key, and the
    provider has no divisions for this country. Both mean the same next step —
    enter the competition by hand — and neither is a fault.
    """

    available: bool
    reason: str | None = None
    leagues: list[ProviderLeague] = []


class SyncOut(BaseModel):
    created: int
    updated: int
    requests: int
    remaining: int | None


async def _settings(db: Db, ctx: RequestContext, club_id: UUID) -> ClubFeed:
    club = await db.scalar(select(Club).where(Club.id == club_id, Club.tenant_id == ctx.tenant))
    if club is None:
        raise NotFound(object_type="club", object_id=str(club_id))

    # API-Football is a football provider. Offering it to a handball club would
    # be offering to fill their calendar with somebody else's fixtures.
    sport = profile(club.sport)
    if sport.provider != PROVIDER:
        raise ValidationFailed(
            f"There is no league feed for {sport.name.lower()} yet — "
            "fixtures and results are entered by hand.",
            field="sport",
        )

    row = await db.scalar(
        select(ClubFeed).where(ClubFeed.club_id == club_id, ClubFeed.provider == PROVIDER)
    )
    if row is None:
        # Manual until somebody says otherwise. A club that never touches this
        # screen keeps entering its own fixtures, which is the safe default.
        row = ClubFeed(tenant_id=ctx.tenant, club_id=club_id, provider=PROVIDER)
        db.add(row)
        await db.flush()
    return row


@router.get(
    "/clubs/{club_id}/feed", response_model=FeedSettings, summary="League feed settings"
)
async def read_feed(
    club_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(READ))],
) -> FeedSettings:
    from app.core.config import settings

    row = await _settings(db, ctx, club_id)
    out = FeedSettings.model_validate(row)
    out.provider_available = bool(settings.api_football_key.get_secret_value())
    return out


@router.put("/clubs/{club_id}/feed", response_model=FeedSettings, summary="Configure the feed")
async def update_feed(
    club_id: UUID,
    payload: FeedUpdate,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(MANAGE))],
) -> FeedSettings:
    from app.core.config import settings

    row = await _settings(db, ctx, club_id)
    changes = payload.model_dump(exclude_unset=True)

    if changes.get("mode") == "FEED":
        team = changes.get("provider_team_id", row.provider_team_id)
        if not team:
            raise ValidationFailed(
                "Choose the club in the league feed before switching it on.",
                field="provider_team_id",
            )
        if not changes.get("season_year", row.season_year):
            raise ValidationFailed(
                "Set the season the feed should follow.", field="season_year"
            )

    before = {field: getattr(row, field) for field in changes}
    for field, value in changes.items():
        setattr(row, field, value)

    AuditService(db).record(
        ctx,
        action="competitions.feed.configure",
        object_type="club",
        object_id=club_id,
        club_id=club_id,
        before=before,
        after=changes,
    )
    await db.flush()

    out = FeedSettings.model_validate(row)
    out.provider_available = bool(settings.api_football_key.get_secret_value())
    return out


@router.get(
    "/feed/leagues",
    response_model=ProviderCatalogue,
    summary="The divisions the feed covers in a country",
)
async def list_provider_leagues(
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(MANAGE))],
    country: Annotated[str, Query(min_length=2, max_length=2)] = "RO",
) -> ProviderCatalogue:
    """Every division the provider holds for a country, newest season first.

    A club picks its division from this rather than typing one, so there is no
    spelling to get wrong and no ambiguity to resolve later. Where the answer
    is empty the club has learned something true — its league is not covered —
    which is worth a screen of its own rather than an error.
    """
    if not settings.api_football_key:
        return ProviderCatalogue(
            available=False, reason="This platform has no results feed configured."
        )
    try:
        async with ApiFootball() as client:
            rows = await client.leagues(country=COUNTRY_NAMES.get(country.upper(), country))
    except ProviderUnavailable as exc:
        return ProviderCatalogue(available=False, reason=str(exc))

    leagues: list[ProviderLeague] = []
    for row in rows:
        league = row.get("league") or {}
        if not league.get("id"):
            continue
        seasons = [s.get("year") for s in (row.get("seasons") or []) if s.get("year")]
        leagues.append(
            ProviderLeague(
                id=str(league["id"]),
                name=league.get("name") or "",
                country=(row.get("country") or {}).get("name"),
                logo=league.get("logo"),
                season=max(seasons) if seasons else None,
            )
        )
    leagues.sort(key=lambda item: item.name)

    if not leagues:
        return ProviderCatalogue(
            available=False,
            reason="The feed covers no divisions in this country. Add your competition here.",
        )
    return ProviderCatalogue(available=True, leagues=leagues)


@router.get(
    "/feed/leagues/{league_id}/teams",
    response_model=list[ProviderTeam],
    summary="The clubs in one division",
)
async def list_league_teams(
    league_id: str,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(MANAGE))],
    season: Annotated[int, Query(ge=2000, le=2100)],
) -> list[ProviderTeam]:
    """Everyone in that division that season, for the club to point at itself.

    Choosing from a list is the whole point: it removes the only decision that
    could put another club's fixtures on this one's website.
    """
    try:
        async with ApiFootball() as client:
            rows = await client.teams(league=league_id, season=season)
    except ProviderUnavailable as exc:
        raise ValidationFailed(str(exc), field="provider") from exc

    teams = [
        ProviderTeam(
            id=str(row["team"]["id"]),
            name=row["team"].get("name") or "",
            country=row["team"].get("country"),
            logo=row["team"].get("logo"),
            founded=row["team"].get("founded"),
        )
        for row in rows
        if row.get("team")
    ]
    teams.sort(key=lambda team: team.name)
    return teams


@router.get(
    "/feed/teams", response_model=list[ProviderTeam], summary="Find your club in the feed"
)
async def search_teams(
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(MANAGE))],
    q: Annotated[str, Query(min_length=3, max_length=60)],
) -> list[ProviderTeam]:
    """Search the provider's catalogue by name.

    Spends one call from the shared allowance, which is why it needs three
    characters: a search on "a" costs the same as a useful one.
    """
    try:
        async with ApiFootball() as client:
            rows = await client.search_teams(query=q.strip())
    except ProviderUnavailable as exc:
        raise ValidationFailed(str(exc), field="provider") from exc

    return [
        ProviderTeam(
            id=str(row["team"]["id"]),
            name=row["team"].get("name") or "",
            country=row["team"].get("country"),
            logo=row["team"].get("logo"),
            founded=row["team"].get("founded"),
        )
        for row in rows
        if row.get("team")
    ]


class SquadImportOut(BaseModel):
    created: int
    skipped: int
    notes: list[str] = []


@router.post(
    "/clubs/{club_id}/feed/squad",
    response_model=SquadImportOut,
    summary="Bring in the provider's squad for one team",
)
async def import_squad_from_feed(
    club_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(MANAGE))],
    team_id: Annotated[UUID, Query()],
) -> SquadImportOut:
    """Add the players the provider lists for this club, to one of our teams.

    Which team is the club's to say. The provider knows a club has a squad; it
    does not know we hold six, and choosing on its behalf is how a second
    division squad lands in the under-13s.
    """
    feed = await _settings(db, ctx, club_id)
    if not feed.provider_team_id:
        raise ValidationFailed(
            "Connect this club to the results feed first.", field="provider_team_id"
        )

    team = await db.scalar(select(Team).where(Team.id == team_id, Team.club_id == club_id))
    if team is None:
        raise NotFound(object_type="team", object_id=str(team_id))

    season = await db.scalar(
        select(Season).where(Season.club_id == club_id, Season.is_current.is_(True))
    )
    if season is None:
        raise ValidationFailed(
            "This club has no current season, and a registration needs one.", field="season"
        )

    try:
        async with ApiFootball() as client:
            result = await squads.import_squad(
                db,
                client,
                tenant_id=ctx.tenant,
                club_id=club_id,
                team_id=team_id,
                season_id=season.id,
                provider_team_id=feed.provider_team_id,
            )
    except ProviderUnavailable as exc:
        raise ValidationFailed(str(exc), field="provider") from exc

    AuditService(db).record(
        ctx,
        action="players.squad.import",
        object_type="team",
        object_id=team_id,
        club_id=club_id,
        after={"created": result.created, "skipped": result.skipped},
    )
    return SquadImportOut(created=result.created, skipped=result.skipped, notes=result.notes)


@router.post(
    "/clubs/{club_id}/feed/history",
    response_model=SyncOut,
    summary="Pull this club's history and honours",
)
async def sync_history(
    club_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(MANAGE))],
) -> SyncOut:
    """Season-by-season record, plus the club's own facts.

    Separate from the fixtures sync and not on a timer: a finished season's
    table never changes, and a stadium's capacity changes when it is rebuilt.
    Running this nightly would spend a dozen calls to rewrite the same rows.
    """
    from app.core.db import platform_session
    from app.integrations.api_football import sync as syncer

    row = await _settings(db, ctx, club_id)
    if row.mode != "FEED" or not row.provider_team_id:
        raise ValidationFailed(
            "This club is not connected to the league feed yet.", field="mode"
        )

    try:
        async with (
            ApiFootball() as client,
            platform_session(
                reason=f"sync history for club {club_id} from the league feed"
            ) as session,
        ):
            await syncer.sync_club_profile(
                session, client, provider_team_id=row.provider_team_id
            )
            result = await syncer.sync_club_history(
                session, client, provider_team_id=row.provider_team_id
            )
    except ProviderUnavailable as exc:
        raise ValidationFailed(str(exc), field="provider") from exc

    return SyncOut(
        created=result.created,
        updated=result.updated,
        requests=result.requests,
        remaining=result.remaining,
    )


@router.post(
    "/clubs/{club_id}/feed/sync",
    response_model=SyncOut,
    status_code=status.HTTP_200_OK,
    summary="Pull this club's fixtures now",
)
async def sync_now(
    club_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(MANAGE))],
) -> SyncOut:
    """One call, everything this club plays this season.

    Runs on the platform session rather than this one: fixtures and the club
    directory are shared reference data that no tenant owns, and RLS is right
    to refuse a tenant-scoped write to them.
    """
    from app.core.db import platform_session
    from app.integrations.api_football import sync as syncer

    row = await _settings(db, ctx, club_id)
    if row.mode != "FEED" or not row.provider_team_id or not row.season_year:
        raise ValidationFailed(
            "This club is not connected to the league feed yet.", field="mode"
        )

    try:
        async with (
            ApiFootball() as client,
            platform_session(
                reason=f"sync fixtures for club {club_id} from the league feed"
            ) as session,
        ):
            result = await syncer.sync_club_fixtures(
                session,
                client,
                provider_team_id=row.provider_team_id,
                season_year=row.season_year,
            )
            await syncer.sync_events_for_club(
                session, client, provider_team_id=row.provider_team_id
            )
            if row.sync_standings:
                # One call per league the club is actually in, which the
                # fixtures above have just told us — rather than per
                # competition in the catalogue.
                for league_id in await syncer.leagues_played(
                    session, provider_team_id=row.provider_team_id
                ):
                    # The whole division's results, so a table adjusted for
                    # today's round is adjusted for everybody in it.
                    await syncer.sync_league_fixtures(
                        session,
                        client,
                        provider_league=league_id,
                        provider_season=row.season_year,
                    )
                    table = await syncer.sync_standings(
                        session,
                        client,
                        provider_league=league_id,
                        provider_season=row.season_year,
                    )
                    result.created += table.created
                    result.updated += table.updated
                result.requests = client.usage.requests
                result.remaining = client.usage.remaining
    except ProviderUnavailable as exc:
        row.last_error = str(exc)[:500]
        await db.flush()
        raise ValidationFailed(str(exc), field="provider") from exc

    row.last_fixtures_at = datetime.now(UTC)
    row.last_error = None
    await db.flush()

    return SyncOut(
        created=result.created,
        updated=result.updated,
        requests=result.requests,
        remaining=result.remaining,
    )
