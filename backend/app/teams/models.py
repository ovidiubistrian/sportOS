from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantScoped, Timestamped, UUIDPrimaryKey

TEAM_LEVELS = ("FIRST", "RESERVE", "YOUTH", "FUTSAL", "OTHER")
GENDERS = ("MALE", "FEMALE", "MIXED")


class Season(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """A club's season.

    Scoped to the club, not the tenant: a tenant may hold clubs in countries
    with different season calendars.
    """

    __tablename__ = "season"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "club_id"],
            ["club.tenant_id", "club.id"],
            name="fk_season_club",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "club_id", "name", name="uq_season_club_name"),
        UniqueConstraint("tenant_id", "id", name="uq_season_tenant_id_id"),
        # At most one current season per club, enforced by the database.
        Index(
            "uq_season_current_per_club",
            "club_id",
            unique=True,
            postgresql_where="is_current",
        ),
        CheckConstraint("end_date > start_date", name="season_dates_ordered"),
    )

    club_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(32))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(default=False)


class Team(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    __tablename__ = "team"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "club_id"],
            ["club.tenant_id", "club.id"],
            name="fk_team_club",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "club_id", "code", name="uq_team_club_code"),
        UniqueConstraint("tenant_id", "id", name="uq_team_tenant_id_id"),
        CheckConstraint("level IN " + str(TEAM_LEVELS), name="team_level_valid"),
        CheckConstraint("gender IN " + str(GENDERS), name="team_gender_valid"),
        Index("ix_team_club", "tenant_id", "club_id"),
    )

    club_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(16))
    gender: Mapped[str] = mapped_column(String(8), default="MALE")
    age_group: Mapped[str | None] = mapped_column(String(16))
    level: Mapped[str] = mapped_column(String(16), default="YOUTH")
    is_academy: Mapped[bool] = mapped_column(default=True)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    # Which sport this plays. See app/sports/registry.py — resolution is
    # team → club → tenant, so a single-sport club says it once and a CSM
    # running football and handball says it where it differs.
    sport: Mapped[str] = mapped_column(
        String(24), default="FOOTBALL", server_default="FOOTBALL"
    )



# The people on the touchline. Ordered as a club would introduce them, which is
# also the order they are shown in.
TEAM_STAFF_ROLES = (
    "HEAD_COACH",
    "ASSISTANT_COACH",
    "GOALKEEPING_COACH",
    "FITNESS_COACH",
    "ANALYST",
    "PHYSIO",
    "DOCTOR",
    "TEAM_MANAGER",
    "KIT_MANAGER",
    # Club roles rather than touchline ones. They are here because a club
    # thinks of all of these as "staff" and looks for them in one place — and
    # because a press officer belongs on the website exactly as much as the
    # coach does, which is the whole point of the list.
    "PRESS_OFFICER",
    "PRESIDENT",
    "DIRECTOR",
)


class TeamStaff(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """Who runs a team, as the club presents them.

    Separate from a role assignment on purpose. `role_assignment` says what
    somebody may *do* in this software; this says what they *are* to the team,
    and the two are genuinely different: a head coach who never signs in is
    still the head coach, and a volunteer with an admin login is not.

    Attached to a `person`, so a coach who is also a parent and a former player
    is one human being in the club's records rather than three.
    """

    __tablename__ = "team_staff"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "team_id"],
            ["team.tenant_id", "team.id"],
            name="fk_team_staff_team",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["person.tenant_id", "person.id"],
            name="fk_team_staff_person",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "team_id", "person_id", name="uq_team_staff_person"),
        CheckConstraint("role IN " + str(TEAM_STAFF_ROLES), name="team_staff_role_valid"),
        Index("ix_team_staff_team", "tenant_id", "team_id"),
    )

    club_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    team_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    person_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))

    role: Mapped[str] = mapped_column(String(24), default="HEAD_COACH")
    # What the club calls the job, when its own word differs from ours.
    title: Mapped[str | None] = mapped_column(String(80))
    photo_media_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    # Staff appear on the public site only when the club says so. A volunteer
    # physio has not necessarily agreed to be on a website.
    is_public: Mapped[bool] = mapped_column(default=True)
    sort_order: Mapped[int] = mapped_column(default=0)
