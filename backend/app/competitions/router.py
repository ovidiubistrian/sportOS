"""Competitions and fixtures, from the club's side.

A club does three things here: joins a competition for a season, enters its
fixtures, and records results. Everything it touches is shared reference data,
so the rules are stricter than elsewhere in the product — a club may write a
match it is playing in, and nothing else.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import or_, select

from app.api.deps import Db, Requires
from app.audit.service import AuditService
from app.competitions.models import (
    MATCH_STATUSES,
    ROUND_KINDS,
    Competition,
    CompetitionEntry,
    CompetitionSeason,
    DirectoryClub,
    Match,
)
from app.competitions.standings import compute_table
from app.core.context import RequestContext
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.events.base import MatchScheduleChanged
from app.events.publisher import publish
from app.identity.registration import slugify
from app.integrations.api_football import autolink
from app.tenants.models import Club

router = APIRouter(tags=["competitions"])

READ = "teams.team.read"
MANAGE = "teams.team.manage"


class CompetitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key: str
    name: str
    short_name: str | None
    format: str
    scope: str
    tier: int | None


class JoinedCompetition(BaseModel):
    """What entering a competition did, including to the results feed.

    The feed is reported rather than silent because "connected" and "this
    division is not covered" ask completely different things of the club next,
    and it should not have to go looking to find out which one happened.
    """

    competition: CompetitionOut
    feed_connected: bool
    feed_message: str


class ClubRef(BaseModel):
    id: UUID
    name: str
    short_name: str
    crest_url: str | None


class MatchOut(BaseModel):
    id: UUID
    competition_season_id: UUID
    competition_name: str
    home: ClubRef
    away: ClubRef
    round_kind: str
    round_number: int | None
    round_label: str | None
    kickoff_at: datetime | None
    kickoff_is_confirmed: bool
    venue_name: str | None
    status: str
    home_score: int | None
    away_score: int | None
    ticket_url: str | None
    # Whether the club whose admin this is played at home.
    is_home: bool = False


class TableRowOut(BaseModel):
    position: int
    club: ClubRef
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    goal_difference: int
    points: int
    form: list[str]


class SeasonOut(BaseModel):
    """A season the club is actually in — what a fixture form picks from."""

    id: UUID
    competition_id: UUID
    competition_name: str
    competition_format: str
    season_name: str
    is_current: bool


class DirectoryClubIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=160)
    short_name: str | None = Field(default=None, max_length=16)
    city: str | None = Field(default=None, max_length=120)


class JoinCompetition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    club_id: UUID
    competition_id: UUID
    season_name: str = Field(min_length=4, max_length=32)
    start_date: date
    end_date: date


class MatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    club_id: UUID
    competition_season_id: UUID
    opponent_club_id: UUID
    at_home: bool = True
    round_kind: str = "MATCHDAY"
    round_number: int | None = None
    round_label: str | None = Field(default=None, max_length=48)
    kickoff_at: datetime | None = None
    kickoff_is_confirmed: bool = True
    venue_name: str | None = Field(default=None, max_length=160)
    ticket_url: str | None = Field(default=None, max_length=500)

    @field_validator("round_kind")
    @classmethod
    def _known_round(cls, value: str) -> str:
        if value not in ROUND_KINDS:
            raise ValueError(f"must be one of {', '.join(ROUND_KINDS)}")
        return value


class MatchUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kickoff_at: datetime | None = None
    kickoff_is_confirmed: bool | None = None
    venue_name: str | None = Field(default=None, max_length=160)
    ticket_url: str | None = Field(default=None, max_length=500)
    status: str | None = None
    home_score: int | None = Field(default=None, ge=0, le=99)
    away_score: int | None = Field(default=None, ge=0, le=99)

    @field_validator("status")
    @classmethod
    def _known_status(cls, value: str | None) -> str | None:
        if value is not None and value not in MATCH_STATUSES:
            raise ValueError(f"must be one of {', '.join(MATCH_STATUSES)}")
        return value


async def _directory_entry(db: Db, ctx: RequestContext, club_id: UUID) -> DirectoryClub:
    """The club's entry in the platform directory, created on first use.

    A club only needs one when it enters a competition, so it is made here
    rather than at sign-up — most clubs on the platform will be academies that
    never appear in a fixture list.
    """
    club = await db.scalar(select(Club).where(Club.id == club_id, Club.tenant_id == ctx.tenant))
    if club is None:
        raise NotFound(object_type="club", object_id=str(club_id))

    if club.directory_club_id:
        entry = await db.get(DirectoryClub, club.directory_club_id)
        if entry is not None:
            return entry

    slug = slugify(club.display_name)
    existing = await db.scalar(select(DirectoryClub).where(DirectoryClub.slug == slug))
    if existing is None:
        existing = DirectoryClub(
            slug=slug,
            name=club.display_name,
            short_name=club.short_name,
            city=None,
        )
        db.add(existing)
        await db.flush()

    club.directory_club_id = existing.id
    await db.flush()
    return existing


async def _ensure_entered(db: Db, season_id: UUID, *club_ids: UUID) -> None:
    """Enter clubs into a season, skipping the ones already in it."""
    present = set(
        await db.scalars(
            select(CompetitionEntry.directory_club_id).where(
                CompetitionEntry.competition_season_id == season_id,
                CompetitionEntry.directory_club_id.in_(club_ids),
            )
        )
    )
    for club_id in club_ids:
        if club_id not in present:
            db.add(CompetitionEntry(competition_season_id=season_id, directory_club_id=club_id))
    await db.flush()


def _ref(club: DirectoryClub) -> ClubRef:
    return ClubRef(
        id=club.id,
        name=club.name,
        short_name=club.short_name,
        crest_url=club.crest_url,
    )


@router.get(
    "/competitions", response_model=list[CompetitionOut], summary="Competitions on offer"
)
async def list_competitions(
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(READ))],
    country_code: str | None = None,
) -> list[CompetitionOut]:
    """What a club can enter.

    Platform reference data, so this is the same list for everyone — which is
    the point: two clubs in Liga 2 must be choosing the same Liga 2.
    """
    stmt = select(Competition).where(Competition.is_active.is_(True))
    competitions = await db.scalars(stmt.order_by(Competition.sort_order))
    return [CompetitionOut.model_validate(c) for c in competitions]


@router.post(
    "/competitions/join",
    response_model=JoinedCompetition,
    status_code=status.HTTP_201_CREATED,
    summary="Enter a competition for a season",
)
async def join_competition(
    payload: JoinCompetition,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(MANAGE))],
) -> JoinedCompetition:
    competition = await db.get(Competition, payload.competition_id)
    if competition is None:
        raise NotFound(object_type="competition", object_id=str(payload.competition_id))

    # A handball club entering a football league would poison a shared table:
    # competitions and their seasons are platform reference data, so one club's
    # mistake would be visible to every other club in that division.
    club = await db.scalar(
        select(Club).where(Club.id == payload.club_id, Club.tenant_id == ctx.tenant)
    )
    if club is not None and club.sport != competition.sport:
        raise ValidationFailed(
            "That competition is for a different sport.", field="competition_id"
        )

    if payload.end_date <= payload.start_date:
        raise ValidationFailed("A season has to end after it starts.", field="end_date")

    directory = await _directory_entry(db, ctx, payload.club_id)

    season = await db.scalar(
        select(CompetitionSeason).where(
            CompetitionSeason.competition_id == competition.id,
            CompetitionSeason.name == payload.season_name,
        )
    )
    if season is None:
        # The first club to enter a season creates it. Shared afterwards, which
        # is what lets two customers in the same division see one table.
        season = CompetitionSeason(
            competition_id=competition.id,
            name=payload.season_name,
            start_date=payload.start_date,
            end_date=payload.end_date,
            is_current=True,
        )
        db.add(season)
        await db.flush()

    already = await db.scalar(
        select(CompetitionEntry).where(
            CompetitionEntry.competition_season_id == season.id,
            CompetitionEntry.directory_club_id == directory.id,
        )
    )
    if already is not None:
        raise Conflict("This club is already in that competition for the season.")

    db.add(CompetitionEntry(competition_season_id=season.id, directory_club_id=directory.id))
    AuditService(db).record(
        ctx,
        action="competitions.entry.create",
        object_type="club",
        object_id=payload.club_id,
        club_id=payload.club_id,
        after={"competition": competition.key, "season": season.name},
    )
    await db.flush()

    # Entering a league is the only thing the club is asked. Whether the
    # provider covers that league, and whether this club can be identified in
    # it without guessing, is our problem — and both answers are fine.
    link = await autolink.try_link(
        db,
        tenant_id=ctx.tenant,
        club_id=payload.club_id,
        club_name=(club.display_name if club is not None else directory.name),
        season_name=season.name,
        country_code=(club.country_code if club is not None else None),
    )
    return JoinedCompetition(
        competition=CompetitionOut.model_validate(competition),
        feed_connected=link.linked,
        feed_message=link.reason,
    )


@router.get(
    "/competitions/entries",
    response_model=list[SeasonOut],
    summary="Seasons this club is in",
)
async def list_entries(
    club_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(READ))],
) -> list[SeasonOut]:
    club = await db.scalar(select(Club).where(Club.id == club_id, Club.tenant_id == ctx.tenant))
    if club is None or club.directory_club_id is None:
        return []

    rows = (
        await db.execute(
            select(CompetitionSeason, Competition)
            .join(Competition, Competition.id == CompetitionSeason.competition_id)
            .join(
                CompetitionEntry,
                CompetitionEntry.competition_season_id == CompetitionSeason.id,
            )
            .where(CompetitionEntry.directory_club_id == club.directory_club_id)
            .order_by(Competition.sort_order, CompetitionSeason.start_date.desc())
        )
    ).all()

    return [
        SeasonOut(
            id=season.id,
            competition_id=competition.id,
            competition_name=competition.name,
            competition_format=competition.format,
            season_name=season.name,
            is_current=season.is_current,
        )
        for season, competition in rows
    ]


@router.get("/directory/clubs", response_model=list[ClubRef], summary="Find a club to play")
async def search_directory(
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(READ))],
    q: str = "",
    season_id: UUID | None = None,
    limit: int = 20,
) -> list[ClubRef]:
    """Opponents, by name.

    Narrowed to one season's entrants when `season_id` is given, which is what
    a fixture form wants: the clubs in this division, not every club on the
    platform.
    """
    stmt = select(DirectoryClub)
    if season_id is not None:
        stmt = stmt.join(
            CompetitionEntry,
            CompetitionEntry.directory_club_id == DirectoryClub.id,
        ).where(CompetitionEntry.competition_season_id == season_id)
    if q.strip():
        stmt = stmt.where(DirectoryClub.name.ilike(f"%{q.strip()}%"))

    clubs = await db.scalars(stmt.order_by(DirectoryClub.name).limit(min(limit, 100)))
    return [_ref(c) for c in clubs]


@router.post(
    "/directory/clubs",
    response_model=ClubRef,
    status_code=status.HTTP_201_CREATED,
    summary="Add a club to the directory",
)
async def add_directory_club(
    payload: DirectoryClubIn,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(MANAGE))],
) -> ClubRef:
    """Name an opponent that is not on the platform yet.

    Find-or-create by slug rather than reject: two clubs in the same division
    will both try to add the same opponent, and the second one is not making a
    mistake. Returning the existing row means their fixtures point at one club
    instead of two spellings of it, which is what makes a shared table work.
    """
    name = payload.name.strip()
    slug = slugify(name)
    if not slug:
        raise ValidationFailed("That name has no letters in it.", field="name")

    existing = await db.scalar(select(DirectoryClub).where(DirectoryClub.slug == slug))
    if existing is not None:
        return _ref(existing)

    club = DirectoryClub(
        slug=slug,
        name=name,
        short_name=(payload.short_name or "".join(w[0] for w in name.split()[:3]))[:16].upper(),
        city=payload.city,
    )
    db.add(club)
    await db.flush()
    AuditService(db).record(
        ctx,
        action="competitions.directory.create",
        object_type="directory_club",
        object_id=club.id,
        after={"name": club.name},
    )
    return _ref(club)


@router.get("/matches", response_model=list[MatchOut], summary="A club's fixtures")
async def list_matches(
    club_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(READ))],
    upcoming: bool | None = None,
    limit: int = 50,
) -> list[MatchOut]:
    club = await db.scalar(select(Club).where(Club.id == club_id, Club.tenant_id == ctx.tenant))
    if club is None or club.directory_club_id is None:
        return []

    stmt = select(Match).where(
        or_(
            Match.home_club_id == club.directory_club_id,
            Match.away_club_id == club.directory_club_id,
        )
    )
    if upcoming is True:
        stmt = stmt.where(Match.status == "SCHEDULED").order_by(Match.kickoff_at)
    elif upcoming is False:
        stmt = stmt.where(Match.status.in_(("FINISHED", "AWARDED"))).order_by(
            Match.kickoff_at.desc()
        )
    else:
        stmt = stmt.order_by(Match.kickoff_at)

    matches = list(await db.scalars(stmt.limit(min(limit, 200))))
    return await _render(db, matches, club.directory_club_id)


async def _render(db: Db, matches: list[Match], own_id: UUID | None) -> list[MatchOut]:
    if not matches:
        return []
    club_ids = {m.home_club_id for m in matches} | {m.away_club_id for m in matches}
    clubs = {
        c.id: c
        for c in await db.scalars(select(DirectoryClub).where(DirectoryClub.id.in_(club_ids)))
    }
    season_ids = {m.competition_season_id for m in matches}
    names = {
        row[0]: row[1]
        for row in (
            await db.execute(
                select(CompetitionSeason.id, Competition.name)
                .join(Competition, Competition.id == CompetitionSeason.competition_id)
                .where(CompetitionSeason.id.in_(season_ids))
            )
        ).all()
    }
    return [
        MatchOut(
            id=m.id,
            competition_season_id=m.competition_season_id,
            competition_name=names.get(m.competition_season_id, ""),
            home=_ref(clubs[m.home_club_id]),
            away=_ref(clubs[m.away_club_id]),
            round_kind=m.round_kind,
            round_number=m.round_number,
            round_label=m.round_label,
            kickoff_at=m.kickoff_at,
            kickoff_is_confirmed=m.kickoff_is_confirmed,
            venue_name=m.venue_name,
            status=m.status,
            home_score=m.home_score,
            away_score=m.away_score,
            ticket_url=m.ticket_url,
            is_home=m.home_club_id == own_id,
        )
        for m in matches
    ]


@router.post(
    "/matches",
    response_model=MatchOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a fixture",
)
async def create_match(
    payload: MatchCreate,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(MANAGE))],
) -> MatchOut:
    directory = await _directory_entry(db, ctx, payload.club_id)
    opponent = await db.get(DirectoryClub, payload.opponent_club_id)
    if opponent is None:
        raise NotFound(object_type="directory_club")
    if opponent.id == directory.id:
        raise ValidationFailed("A club cannot play itself.", field="opponent_club_id")

    season = await db.get(CompetitionSeason, payload.competition_season_id)
    if season is None:
        raise NotFound(object_type="competition_season")

    # Playing in a season is what being in it means. Without this the opponent
    # stays outside the entry list, the table skips every result against them
    # as a data error, and the club records a season of scores into nothing.
    await _ensure_entered(db, season.id, directory.id, opponent.id)

    match = Match(
        competition_season_id=season.id,
        home_club_id=directory.id if payload.at_home else opponent.id,
        away_club_id=opponent.id if payload.at_home else directory.id,
        round_kind=payload.round_kind,
        round_number=payload.round_number,
        round_label=payload.round_label,
        kickoff_at=payload.kickoff_at,
        kickoff_is_confirmed=payload.kickoff_is_confirmed,
        venue_name=payload.venue_name,
        ticket_url=payload.ticket_url,
        status="SCHEDULED",
    )
    db.add(match)
    await db.flush()

    AuditService(db).record(
        ctx,
        action="competitions.match.create",
        object_type="match",
        object_id=match.id,
        club_id=payload.club_id,
        after={"opponent": opponent.name, "at_home": payload.at_home},
    )
    # The club adds a fixture so supporters can see it. Purging the site's cache
    # is the difference between "when the time comes" and "in an hour or so".
    publish(db, MatchScheduleChanged.of(payload.club_id, tenant_id=ctx.tenant))
    return (await _render(db, [match], directory.id))[0]


@router.patch("/matches/{match_id}", response_model=MatchOut, summary="Update a fixture")
async def update_match(
    match_id: UUID,
    payload: MatchUpdate,
    club_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(MANAGE))],
) -> MatchOut:
    """Change a fixture, or record its result.

    A club may only touch a match it is playing in. Matches are shared reference
    data, so without that check any club could rewrite any other club's results.
    """
    match = await db.get(Match, match_id)
    if match is None:
        raise NotFound(object_type="match", object_id=str(match_id))

    directory = await _directory_entry(db, ctx, club_id)
    if directory.id not in (match.home_club_id, match.away_club_id):
        # 404 rather than 403: whether a fixture exists is not this club's
        # business either.
        raise NotFound(object_type="match", object_id=str(match_id))

    if match.source != "CLUB":
        # One writer per row. This fixture is kept in step with the provider,
        # and an edit here would survive exactly until the next sync — which is
        # worse than being told no.
        raise ValidationFailed(
            "This fixture comes from the league feed and updates automatically.",
            field="source",
        )

    changes = payload.model_dump(exclude_unset=True)
    before = {field: getattr(match, field) for field in changes}
    for field, value in changes.items():
        setattr(match, field, value)

    # A score and a status have to agree — the database enforces it, and saying
    # so here turns a 500 into a sentence the club can act on.
    played = match.status in ("FINISHED", "AWARDED", "LIVE")
    has_score = match.home_score is not None and match.away_score is not None
    if played and not has_score:
        raise ValidationFailed("A finished match needs both scores.", field="home_score")
    if has_score and not played:
        raise ValidationFailed(
            "Set the status to finished before entering a score.", field="status"
        )

    AuditService(db).record(
        ctx,
        action="competitions.match.update",
        object_type="match",
        object_id=match.id,
        club_id=club_id,
        before=before,
        after=changes,
    )
    publish(db, MatchScheduleChanged.of(club_id, tenant_id=ctx.tenant))
    await db.flush()
    return (await _render(db, [match], directory.id))[0]


@router.delete(
    "/matches/{match_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a fixture",
)
async def delete_match(
    match_id: UUID,
    club_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(MANAGE))],
) -> None:
    """Take a fixture off the calendar.

    Deleted rather than archived, unlike a team: a fixture entered by mistake
    never happened, and leaving it as a hidden row would still count toward the
    season it was filed against. A played one cannot be removed — that is a
    result somebody is relying on, and correcting it is what the result editor
    is for.
    """
    match = await db.get(Match, match_id)
    if match is None:
        raise NotFound(object_type="match", object_id=str(match_id))

    directory = await _directory_entry(db, ctx, club_id)
    if directory.id not in (match.home_club_id, match.away_club_id):
        raise NotFound(object_type="match", object_id=str(match_id))

    if match.source != "CLUB":
        raise ValidationFailed(
            "This fixture comes from the league feed and cannot be removed here.",
            field="source",
        )
    if match.status in ("FINISHED", "AWARDED"):
        raise ValidationFailed(
            "A played match cannot be removed. Change the result instead.",
            field="status",
        )

    AuditService(db).record(
        ctx,
        action="competitions.match.delete",
        object_type="match",
        object_id=match.id,
        club_id=club_id,
        before={
            "home": str(match.home_club_id),
            "away": str(match.away_club_id),
            "kickoff_at": match.kickoff_at,
        },
    )
    await db.delete(match)
    publish(db, MatchScheduleChanged.of(club_id, tenant_id=ctx.tenant))
    await db.flush()


@router.get(
    "/competitions/{season_id}/table",
    response_model=list[TableRowOut],
    summary="League table",
)
async def table(
    season_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(READ))],
) -> list[TableRowOut]:
    rows = await compute_table(db, season_id)
    return [
        TableRowOut(
            position=index + 1,
            club=ClubRef(
                id=row.club_id,
                name=row.club_name,
                short_name=row.club_short_name,
                crest_url=row.crest_url,
            ),
            played=row.played,
            won=row.won,
            drawn=row.drawn,
            lost=row.lost,
            goals_for=row.goals_for,
            goals_against=row.goals_against,
            goal_difference=row.goal_difference,
            points=row.points,
            form=row.form,
        )
        for index, row in enumerate(rows)
    ]
