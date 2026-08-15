"""Which sport is this?

One question, asked in three places with three different things in hand: a
team, a club, or nothing but the tenant. Answering it consistently is the whole
job of this module — the rules themselves live in `registry`.

The fallback chain is team → club → tenant, and it exists so that saying it
once is enough. A handball-only club sets its sport on the club and every team
inherits; a CSM that runs football and handball sets it per team and the club's
value is simply what a new team starts as.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.sports.registry import DEFAULT_SPORT, SportProfile, profile
from app.teams.models import Team
from app.tenants.models import Club, Tenant


async def sport_of_team(session: AsyncSession, team_id: UUID) -> SportProfile:
    """The rules that govern one team's fixtures, squad and table."""
    row = await session.scalar(select(Team.sport).where(Team.id == team_id))
    return profile(row)


async def sport_of_club(session: AsyncSession, club_id: UUID) -> SportProfile:
    row = await session.scalar(select(Club.sport).where(Club.id == club_id))
    return profile(row)


async def sport_of_tenant(session: AsyncSession, tenant_id: UUID) -> SportProfile:
    row = await session.scalar(select(Tenant.sport).where(Tenant.id == tenant_id))
    return profile(row)


async def default_for_new_team(session: AsyncSession, club_id: UUID) -> str:
    """What a team created in this club should play, unless told otherwise."""
    row = await session.scalar(select(Club.sport).where(Club.id == club_id))
    return row or DEFAULT_SPORT


async def sports_in_club(session: AsyncSession, club_id: UUID) -> list[str]:
    """Every sport this club actually fields a team in.

    Used to decide whether the club is worth showing a sport chooser at all: a
    club with one sport should never be asked which one, on any screen.
    """
    rows = await session.scalars(
        select(Team.sport).where(Team.club_id == club_id).distinct()
    )
    return sorted({row for row in rows if row})
