from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantScoped, Timestamped, UUIDPrimaryKey
from app.sports.registry import ALL_POSITIONS

PLAYER_STATUSES = ("TRIAL", "REGISTERED", "LOANED_OUT", "INACTIVE", "DEPARTED")
# Every position across every sport we support; the sport profile decides
# which ones a given squad may actually choose from.
POSITIONS = ALL_POSITIONS
FEET = ("LEFT", "RIGHT", "BOTH")
REGISTRATION_KINDS = ("PERMANENT", "LOAN", "DUAL", "TRIAL")


class Player(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """A person's playing attachment to a club.

    Identity lives on `person`; this row holds only what is true of them *as a
    player at this club*. A player who is also a supporter and a parent is one
    person with three attachments. See ADR-0004.
    """

    __tablename__ = "player"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "club_id"],
            ["club.tenant_id", "club.id"],
            name="fk_player_club",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["person.tenant_id", "person.id"],
            name="fk_player_person",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "club_id", "person_id", name="uq_player_person_club"),
        UniqueConstraint("tenant_id", "id", name="uq_player_tenant_id_id"),
        CheckConstraint("status IN " + str(PLAYER_STATUSES), name="player_status_valid"),
        CheckConstraint(
            "preferred_foot IS NULL OR preferred_foot IN " + str(FEET),
            name="player_foot_valid",
        ),
        Index("ix_player_club_status", "tenant_id", "club_id", "status"),
    )

    club_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    person_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))

    status: Mapped[str] = mapped_column(String(16), default="REGISTERED")
    primary_position: Mapped[str | None] = mapped_column(String(12))
    secondary_positions: Mapped[list[str]] = mapped_column(
        ARRAY(String(12)), default=list
    )
    preferred_foot: Mapped[str | None] = mapped_column(String(8))

    federation_id: Mapped[str | None] = mapped_column(String(64))
    # The squad photograph. On the player, not the person: it is a picture of
    # them in this club's kit, and a person at two clubs has two of them.
    photo_media_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    joined_club_on: Mapped[date | None] = mapped_column(Date)
    left_club_on: Mapped[date | None] = mapped_column(Date)


class PlayerRegistration(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """Player ↔ team ↔ season, with history.

    Registrations are never overwritten: a player moving from U15 to U17 ends
    one row and starts another, so "which team was he in last March?" stays
    answerable.
    """

    __tablename__ = "player_registration"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "player_id"],
            ["player.tenant_id", "player.id"],
            name="fk_registration_player",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "team_id"],
            ["team.tenant_id", "team.id"],
            name="fk_registration_team",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "season_id"],
            ["season.tenant_id", "season.id"],
            name="fk_registration_season",
            ondelete="RESTRICT",
        ),
        # One shirt number per team per season, among live registrations only.
        Index(
            "uq_registration_shirt",
            "team_id",
            "season_id",
            "shirt_number",
            unique=True,
            postgresql_where="ended_on IS NULL AND shirt_number IS NOT NULL",
        ),
        # A player is registered to a team once per season at a time.
        Index(
            "uq_registration_active",
            "player_id",
            "team_id",
            "season_id",
            unique=True,
            postgresql_where="ended_on IS NULL",
        ),
        Index(
            "ix_registration_team_active",
            "tenant_id",
            "team_id",
            "season_id",
            postgresql_where="ended_on IS NULL",
        ),
        CheckConstraint("kind IN " + str(REGISTRATION_KINDS), name="registration_kind_valid"),
        CheckConstraint(
            "shirt_number IS NULL OR (shirt_number BETWEEN 1 AND 99)",
            name="registration_shirt_range",
        ),
    )

    player_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    team_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    season_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))

    shirt_number: Mapped[int | None] = mapped_column(SmallInteger)
    kind: Mapped[str] = mapped_column(String(16), default="PERMANENT")
    registered_on: Mapped[date] = mapped_column(Date)
    ended_on: Mapped[date | None] = mapped_column(Date)
    ended_reason: Mapped[str | None] = mapped_column(String(120))
