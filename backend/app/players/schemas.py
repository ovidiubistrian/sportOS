"""Request and response contracts for the players module.

Note what is absent: no schema declares `tenant_id`. Tenancy is context, never
input. `tests/isolation/test_no_tenant_in_schemas.py` enforces that.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.players.models import FEET, PLAYER_STATUSES, POSITIONS


class TeamSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    code: str
    age_group: str | None = None


class PlayerSummary(BaseModel):
    """The list-row shape. Deliberately small: a 500-row page must stay cheap."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    person_id: UUID
    display_name: str
    status: str
    primary_position: str | None
    shirt_number: int | None = None
    team: TeamSummary | None = None
    birth_date: date | None = None
    photo_url: str | None = None


class PlayerDetail(PlayerSummary):
    first_name: str
    last_name: str
    secondary_positions: list[str] = Field(default_factory=list)
    preferred_foot: str | None = None
    nationality: list[str] = Field(default_factory=list)
    federation_id: str | None = None
    photo_media_id: UUID | None = None
    joined_club_on: date | None = None
    left_club_on: date | None = None
    club_id: UUID
    created_at: datetime
    updated_at: datetime


class PlayerCreate(BaseModel):
    club_id: UUID
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    birth_date: date | None = None
    nationality: list[str] = Field(default_factory=list, max_length=3)
    email: str | None = None

    team_id: UUID | None = None
    season_id: UUID | None = None
    shirt_number: int | None = Field(default=None, ge=1, le=99)

    primary_position: str | None = None
    secondary_positions: list[str] = Field(default_factory=list, max_length=4)
    preferred_foot: str | None = None
    federation_id: str | None = Field(default=None, max_length=64)
    joined_club_on: date | None = None

    @field_validator("primary_position", "preferred_foot")
    @classmethod
    def _known_enum(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        # Every sport's vocabulary, not just this player's sport. The schema
        # does not know which team they are in — and a position list is a
        # helpful narrowing, not a safety boundary. The admin UI offers only
        # the team's own sport, which is where the narrowing belongs.
        allowed = POSITIONS if info.field_name == "primary_position" else FEET
        if value not in allowed:
            raise ValueError(f"must be one of {', '.join(allowed)}")
        return value

    @field_validator("secondary_positions")
    @classmethod
    def _known_positions(cls, value: list[str]) -> list[str]:
        unknown = set(value) - set(POSITIONS)
        if unknown:
            raise ValueError(f"unknown positions: {', '.join(sorted(unknown))}")
        return value

    @field_validator("birth_date")
    @classmethod
    def _plausible_birth_date(cls, value: date | None) -> date | None:
        if value is None:
            return None
        if value > date.today():
            raise ValueError("birth date cannot be in the future")
        if value.year < 1920:
            raise ValueError("birth date is implausible")
        return value


class PlayerUpdate(BaseModel):
    """PATCH semantics: an absent key means unchanged, an explicit null clears.

    The first four are the person's, not the player's — a club that mistyped a
    name at registration has to be able to fix it, and making them go and find a
    separate "people" screen for a typo they made here is not a boundary worth
    defending.
    """

    model_config = ConfigDict(extra="forbid")

    first_name: str | None = Field(default=None, min_length=1, max_length=120)
    last_name: str | None = Field(default=None, min_length=1, max_length=120)
    birth_date: date | None = None
    nationality: list[str] | None = Field(default=None, max_length=3)

    status: str | None = None
    photo_media_id: UUID | None = None
    primary_position: str | None = None
    secondary_positions: list[str] | None = None
    preferred_foot: str | None = None
    federation_id: str | None = None
    photo_media_id: UUID | None = None
    joined_club_on: date | None = None
    left_club_on: date | None = None

    @field_validator("status")
    @classmethod
    def _known_status(cls, value: str | None) -> str | None:
        if value is not None and value not in PLAYER_STATUSES:
            raise ValueError(f"must be one of {', '.join(PLAYER_STATUSES)}")
        return value


class PlayerFilters(BaseModel):
    club_id: UUID | None = None
    team_id: UUID | None = None
    season_id: UUID | None = None
    status: str | None = None
    q: str | None = None


class RegistrationChange(BaseModel):
    """Move a player to a squad, or change their number.

    Not a PATCH on the player: registrations carry history, so this ends the
    current one and opens another rather than editing a row. `team_id: null`
    takes the player out of a squad without putting them in a new one.
    """

    model_config = ConfigDict(extra="forbid")

    team_id: UUID | None = None
    season_id: UUID | None = None
    shirt_number: int | None = Field(default=None, ge=1, le=99)
