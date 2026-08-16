from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from app.api.deps import Db, Requires, scoped_filter
from app.audit.service import AuditService
from app.core.context import RequestContext
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.identity.models import Person
from app.sports.registry import SPORT_KEYS
from app.sports.service import default_for_new_team
from app.teams.models import (
    GENDERS,
    TEAM_LEVELS,
    TEAM_STAFF_ROLES,
    Season,
    Team,
    TeamStaff,
)
from app.tenants.models import Club

router = APIRouter(tags=["teams"])

READ = "teams.team.read"


class TeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    club_id: UUID
    name: str
    code: str
    gender: str
    age_group: str | None
    level: str
    is_academy: bool
    status: str
    sport: str


class SeasonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    club_id: UUID
    name: str
    is_current: bool


@router.get("/teams", response_model=list[TeamOut], summary="List teams")
async def list_teams(
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(READ))],
    club_id: Annotated[UUID | None, Query()] = None,
) -> list[TeamOut]:
    scope = scoped_filter(ctx, READ)

    stmt = select(Team).where(Team.tenant_id == ctx.tenant, Team.status == "ACTIVE")
    if club_id is not None:
        stmt = stmt.where(Team.club_id == club_id)

    # A team-scoped coach sees their own teams, not the club's.
    if not scope.unrestricted:
        if scope.is_empty:
            return []
        conditions = []
        if scope.club_ids:
            conditions.append(Team.club_id.in_(scope.club_ids))
        if scope.team_ids:
            conditions.append(Team.id.in_(scope.team_ids))
        from sqlalchemy import or_

        stmt = stmt.where(or_(*conditions))

    rows = await db.scalars(stmt.order_by(Team.name))
    return [TeamOut.model_validate(row) for row in rows]


@router.get("/seasons", response_model=list[SeasonOut], summary="List seasons")
async def list_seasons(
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires("clubs.club.read"))],
    club_id: Annotated[UUID | None, Query()] = None,
) -> list[SeasonOut]:
    stmt = select(Season).where(Season.tenant_id == ctx.tenant)
    if club_id is not None:
        stmt = stmt.where(Season.club_id == club_id)
    rows = await db.scalars(stmt.order_by(Season.start_date.desc()))
    return [SeasonOut.model_validate(row) for row in rows]


class TeamCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    club_id: UUID
    name: str = Field(min_length=2, max_length=120)
    # Short, because it is what appears on a squad badge and in a table cell.
    code: str = Field(min_length=1, max_length=16)
    gender: str = "MALE"
    age_group: str | None = Field(default=None, max_length=16)
    level: str = "YOUTH"
    is_academy: bool = True
    # Absent means "whatever this club plays" — a single-sport club never says
    # it, and a multi-sport one says it per team.
    sport: str | None = None

    @field_validator("code")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("gender")
    @classmethod
    def _known_gender(cls, value: str) -> str:
        if value not in GENDERS:
            raise ValueError(f"must be one of {', '.join(GENDERS)}")
        return value

    @field_validator("level")
    @classmethod
    def _known_level(cls, value: str) -> str:
        if value not in TEAM_LEVELS:
            raise ValueError(f"must be one of {', '.join(TEAM_LEVELS)}")
        return value


@router.post(
    "/teams",
    response_model=TeamOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a team",
)
async def create_team(
    payload: TeamCreate,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires("teams.team.manage"))],
) -> TeamOut:
    """Add a squad.

    A club's first act after signing up is usually listing its teams, so this
    is deliberately minimal: a name and a code. Everything else has a sensible
    default and can be changed later.
    """
    club = await db.scalar(
        select(Club).where(Club.id == payload.club_id, Club.tenant_id == ctx.tenant)
    )
    if club is None:
        raise NotFound(object_type="club", object_id=str(payload.club_id))

    duplicate = await db.scalar(
        select(Team.id).where(
            Team.tenant_id == ctx.tenant,
            Team.club_id == payload.club_id,
            Team.code == payload.code,
        )
    )
    if duplicate is not None:
        raise Conflict(f"There is already a team with the code {payload.code}.", field="code")

    if payload.sport is not None and payload.sport not in SPORT_KEYS:
        raise ValidationFailed("That sport is not one the platform supports.", field="sport")

    team = Team(
        tenant_id=ctx.tenant,
        club_id=payload.club_id,
        name=payload.name.strip(),
        code=payload.code,
        gender=payload.gender,
        age_group=payload.age_group,
        level=payload.level,
        is_academy=payload.is_academy,
        status="ACTIVE",
        # Inherited from the club unless this team is the exception, which is
        # what makes a football club never see the question.
        sport=payload.sport or await default_for_new_team(db, payload.club_id),
    )
    db.add(team)
    await db.flush()

    AuditService(db).record(
        ctx,
        action="teams.team.create",
        object_type="team",
        object_id=team.id,
        club_id=payload.club_id,
        after={"name": team.name, "code": team.code, "age_group": team.age_group},
    )
    return TeamOut.model_validate(team)


class TeamUpdate(BaseModel):
    """PATCH semantics: an absent key means unchanged."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=120)
    code: str | None = Field(default=None, min_length=1, max_length=16)
    gender: str | None = None
    age_group: str | None = Field(default=None, max_length=16)
    level: str | None = None
    is_academy: bool | None = None
    status: str | None = None
    sport: str | None = None

    @field_validator("sport")
    @classmethod
    def _known_sport(cls, value: str | None) -> str | None:
        if value is not None and value not in SPORT_KEYS:
            raise ValueError("That sport is not one the platform supports.")
        return value

    @field_validator("code")
    @classmethod
    def _upper_code(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else value

    @field_validator("gender")
    @classmethod
    def _gender(cls, value: str | None) -> str | None:
        if value is not None and value not in GENDERS:
            raise ValueError(f"must be one of {', '.join(GENDERS)}")
        return value

    @field_validator("level")
    @classmethod
    def _level(cls, value: str | None) -> str | None:
        if value is not None and value not in TEAM_LEVELS:
            raise ValueError(f"must be one of {', '.join(TEAM_LEVELS)}")
        return value

    @field_validator("status")
    @classmethod
    def _status(cls, value: str | None) -> str | None:
        if value is not None and value not in ("ACTIVE", "ARCHIVED"):
            raise ValueError("must be one of ACTIVE, ARCHIVED")
        return value


@router.patch("/teams/{team_id}", response_model=TeamOut, summary="Update a team")
async def update_team(
    team_id: UUID,
    payload: TeamUpdate,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires("teams.team.manage"))],
) -> TeamOut:
    """Rename a squad, move its age group, or archive it.

    Archived rather than deleted: a team with a season of registrations and
    results behind it is history, and deleting it would orphan all of them.
    `GET /teams` returns only active ones, so archiving is what "remove" means
    from the club's side.
    """
    team = await db.scalar(select(Team).where(Team.id == team_id, Team.tenant_id == ctx.tenant))
    if team is None:
        raise NotFound(object_type="team", object_id=str(team_id))

    changes = payload.model_dump(exclude_unset=True)
    if "code" in changes and changes["code"] != team.code:
        duplicate = await db.scalar(
            select(Team.id).where(
                Team.tenant_id == ctx.tenant,
                Team.club_id == team.club_id,
                Team.code == changes["code"],
                Team.id != team.id,
            )
        )
        if duplicate is not None:
            raise Conflict(
                f"There is already a team with the code {changes['code']}.", field="code"
            )

    before = {field: getattr(team, field) for field in changes}
    for field, value in changes.items():
        setattr(team, field, value)
    if isinstance(team.name, str):
        team.name = team.name.strip()

    AuditService(db).record(
        ctx,
        action="teams.team.update",
        object_type="team",
        object_id=team.id,
        club_id=team.club_id,
        before=before,
        after=changes,
    )
    await db.flush()
    return TeamOut.model_validate(team)


class SeasonCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    club_id: UUID
    name: str = Field(min_length=4, max_length=32)
    start_date: date
    end_date: date
    is_current: bool = True


@router.post(
    "/seasons",
    response_model=SeasonOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a season",
)
async def create_season(
    payload: SeasonCreate,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires("clubs.season.manage"))],
) -> SeasonOut:
    """Open a season.

    Nothing about a squad means anything without one: a player is not simply
    "in the U15", they are registered to the U15 *for a season*, which is what
    makes last year's squad list still answerable next year.

    A club therefore needs one before it can register anybody — a gap the demo
    build found, because it went through the same calls a real club does.
    """
    club = await db.scalar(
        select(Club).where(Club.id == payload.club_id, Club.tenant_id == ctx.tenant)
    )
    if club is None:
        raise NotFound(object_type="club", object_id=str(payload.club_id))

    if payload.end_date <= payload.start_date:
        raise ValidationFailed("A season has to end after it starts.", field="end_date")

    if payload.is_current:
        # At most one current season per club, and the database enforces it too.
        # Standing the old one down here means a club can open next season
        # without first remembering to close this one.
        existing = await db.scalars(
            select(Season).where(
                Season.tenant_id == ctx.tenant,
                Season.club_id == payload.club_id,
                Season.is_current.is_(True),
            )
        )
        for season in existing:
            season.is_current = False
        await db.flush()

    season = Season(
        tenant_id=ctx.tenant,
        club_id=payload.club_id,
        name=payload.name.strip(),
        start_date=payload.start_date,
        end_date=payload.end_date,
        is_current=payload.is_current,
    )
    db.add(season)
    await db.flush()

    AuditService(db).record(
        ctx,
        action="clubs.season.create",
        object_type="season",
        object_id=season.id,
        club_id=payload.club_id,
        after={"name": season.name, "is_current": season.is_current},
    )
    return SeasonOut.model_validate(season)


# --- team staff -------------------------------------------------------------
#
# Who runs a team, as the club presents them. Deliberately not the same thing as
# a role assignment: `role_assignment` says what somebody may do in this
# software, and this says what they are to the team. A head coach who never
# signs in is still the head coach.


class TeamStaffOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    team_id: UUID
    person_id: UUID
    name: str
    role: str
    title: str | None
    photo_media_id: UUID | None
    is_public: bool
    sort_order: int


class TeamStaffIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Either an existing person, or a name to create one from. A club appointing
    # a coach who is already a parent in the system should not get a second row
    # for the same human.
    person_id: UUID | None = None
    first_name: str | None = Field(default=None, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)

    role: str = Field(default="HEAD_COACH")
    title: str | None = Field(default=None, max_length=80)
    photo_media_id: UUID | None = None
    is_public: bool = True
    sort_order: int = 0

    @field_validator("role")
    @classmethod
    def known_role(cls, value: str) -> str:
        if value not in TEAM_STAFF_ROLES:
            raise ValueError(f"Role must be one of {', '.join(TEAM_STAFF_ROLES)}.")
        return value


class TeamStaffChanges(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str | None = None
    title: str | None = Field(default=None, max_length=80)
    photo_media_id: UUID | None = None
    is_public: bool | None = None
    sort_order: int | None = None

    @field_validator("role")
    @classmethod
    def known_role(cls, value: str | None) -> str | None:
        if value is not None and value not in TEAM_STAFF_ROLES:
            raise ValueError(f"Role must be one of {', '.join(TEAM_STAFF_ROLES)}.")
        return value


async def _team_or_404(db: Db, ctx: RequestContext, team_id: UUID) -> Team:
    team = await db.scalar(select(Team).where(Team.id == team_id, Team.tenant_id == ctx.tenant))
    if team is None:
        raise NotFound(object_type="team", object_id=str(team_id))
    return team


async def _as_out(db: Db, row: TeamStaff) -> TeamStaffOut:
    person = await db.get(Person, row.person_id)
    return TeamStaffOut(
        id=row.id,
        team_id=row.team_id,
        person_id=row.person_id,
        name=person.display_name if person else "—",
        role=row.role,
        title=row.title,
        photo_media_id=row.photo_media_id,
        is_public=row.is_public,
        sort_order=row.sort_order,
    )


@router.get(
    "/teams/{team_id}/staff",
    response_model=list[TeamStaffOut],
    summary="Who runs this team",
)
async def list_team_staff(
    team_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires("staff.profile.read"))],
) -> list[TeamStaffOut]:
    await _team_or_404(db, ctx, team_id)
    rows = await db.scalars(
        select(TeamStaff)
        .where(TeamStaff.tenant_id == ctx.tenant, TeamStaff.team_id == team_id)
        .order_by(TeamStaff.sort_order)
    )
    return [await _as_out(db, row) for row in rows]


@router.post(
    "/teams/{team_id}/staff",
    response_model=TeamStaffOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add somebody to a team's staff",
)
async def add_team_staff(
    team_id: UUID,
    payload: TeamStaffIn,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires("staff.profile.manage"))],
) -> TeamStaffOut:
    team = await _team_or_404(db, ctx, team_id)

    if payload.person_id is not None:
        person = await db.scalar(
            select(Person).where(Person.id == payload.person_id, Person.tenant_id == ctx.tenant)
        )
        if person is None:
            raise NotFound(object_type="person", object_id=str(payload.person_id))
    else:
        if not payload.first_name or not payload.last_name:
            raise ValidationFailed("A name is needed.", field="first_name")
        person = Person(
            tenant_id=ctx.tenant,
            first_name=payload.first_name.strip(),
            last_name=payload.last_name.strip(),
            display_name=f"{payload.first_name} {payload.last_name}".strip(),
            source="STAFF_ENTRY",
        )
        db.add(person)
        await db.flush()

    existing = await db.scalar(
        select(TeamStaff).where(
            TeamStaff.tenant_id == ctx.tenant,
            TeamStaff.team_id == team_id,
            TeamStaff.person_id == person.id,
        )
    )
    if existing is not None:
        raise Conflict("That person is already on this team's staff.")

    row = TeamStaff(
        tenant_id=ctx.tenant,
        club_id=team.club_id,
        team_id=team_id,
        person_id=person.id,
        role=payload.role,
        title=payload.title,
        photo_media_id=payload.photo_media_id,
        is_public=payload.is_public,
        sort_order=payload.sort_order,
    )
    db.add(row)
    await db.flush()

    AuditService(db).record(
        ctx,
        action="staff.profile.create",
        object_type="team_staff",
        object_id=row.id,
        club_id=team.club_id,
        after={"role": row.role, "person_id": str(person.id)},
    )
    return await _as_out(db, row)


@router.patch(
    "/teams/{team_id}/staff/{staff_id}",
    response_model=TeamStaffOut,
    summary="Edit a staff member",
)
async def update_team_staff(
    team_id: UUID,
    staff_id: UUID,
    payload: TeamStaffChanges,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires("staff.profile.manage"))],
) -> TeamStaffOut:
    row = await db.scalar(
        select(TeamStaff).where(
            TeamStaff.id == staff_id,
            TeamStaff.team_id == team_id,
            TeamStaff.tenant_id == ctx.tenant,
        )
    )
    if row is None:
        raise NotFound(object_type="team_staff", object_id=str(staff_id))

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)

    AuditService(db).record(
        ctx,
        action="staff.profile.update",
        object_type="team_staff",
        object_id=row.id,
        club_id=row.club_id,
        after=payload.model_dump(exclude_unset=True, mode="json"),
    )
    return await _as_out(db, row)


@router.delete(
    "/teams/{team_id}/staff/{staff_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a staff member",
)
async def remove_team_staff(
    team_id: UUID,
    staff_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires("staff.profile.manage"))],
) -> None:
    """Removes them from this team, not from the club's records.

    The `person` stays: they may be a parent, a former player, or on another
    team's staff, and deleting the human because a job ended would take those
    with it.
    """
    row = await db.scalar(
        select(TeamStaff).where(
            TeamStaff.id == staff_id,
            TeamStaff.team_id == team_id,
            TeamStaff.tenant_id == ctx.tenant,
        )
    )
    if row is None:
        raise NotFound(object_type="team_staff", object_id=str(staff_id))

    AuditService(db).record(
        ctx,
        action="staff.profile.delete",
        object_type="team_staff",
        object_id=row.id,
        club_id=row.club_id,
        before={"role": row.role, "person_id": str(row.person_id)},
    )
    await db.delete(row)
