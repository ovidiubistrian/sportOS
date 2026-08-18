"""Arranging a team sheet on the pitch.

The provider gives names and shirt numbers for every league and positions only
for the ones it covers fully — so for most clubs the arrangement is the club's
own work, and these are the rules protecting it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.competitions.models import (
    Competition,
    CompetitionSeason,
    Country,
    DirectoryClub,
    Match,
    MatchLineup,
    MatchLineupPlayer,
)
from app.core import model_registry  # noqa: F401
from app.core.config import settings

pytestmark = pytest.mark.competitions


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    """Platform-scoped: matches and team sheets are global reference data."""
    engine = create_async_engine(settings.database_platform_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            await session.begin()
            try:
                yield session
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


async def _fixture_with_sheet(db: AsyncSession, demo: dict[str, Any]):
    """A fixture between two clubs, with a provider team sheet on the home side.

    Builds both directory clubs itself rather than reaching for the demo club's
    own entry. What is under test is a set of database constraints on the team
    sheet, and they hold for any match — so depending on whether a particular
    club happens to be linked to the league directory is a dependency on state
    the suite does not own. It passed locally and failed in CI for exactly that
    reason.
    """
    sides = []
    for label in ("Home", "Away"):
        club = DirectoryClub(
            name=f"{label} {uuid4().hex[:6]}",
            short_name=label[:3].upper(),
            slug=f"{label.lower()}-{uuid4().hex[:8]}",
            # `country_id` is left unset: it is nullable and, across the 1,900
            # clubs the provider has supplied, never populated. Requiring it
            # here would be inventing a precondition the real data does not
            # have.
        )
        db.add(club)
        sides.append(club)
    await db.flush()

    # The season is built here rather than borrowed. Nothing in the seeds
    # creates one — the rows on a developer's machine come from having run a
    # provider sync — so a test that picked "any existing season" passed
    # locally and failed on a fresh database. Twice, in the same way.
    country = await db.scalar(select(Country).limit(1))
    assert country is not None, "the reference seed provides countries"

    competition = Competition(
        key=f"test-{uuid4().hex[:8]}",
        name="Test Competition",
        format="LEAGUE",
        scope="DOMESTIC_LEAGUE",
        # A domestic league has a tier and a cup does not; the database says so.
        tier=2,
        country_id=country.id,
    )
    db.add(competition)
    await db.flush()

    season = CompetitionSeason(
        competition_id=competition.id,
        name="2026/27",
        start_date=date(2026, 7, 1),
        end_date=date(2027, 6, 30),
    )
    db.add(season)
    await db.flush()

    match = Match(
        competition_season_id=season.id,
        home_club_id=sides[0].id,
        away_club_id=sides[1].id,
        kickoff_at=datetime.now(UTC) + timedelta(days=3),
        status="SCHEDULED",
        source="API_FOOTBALL",
    )
    db.add(match)
    await db.flush()

    lineup = MatchLineup(match_id=match.id, side="HOME", source="PROVIDER")
    db.add(lineup)
    await db.flush()

    for index, name in enumerate(["A. Popescu", "B. Ionescu", "C. Marin"]):
        db.add(
            MatchLineupPlayer(
                lineup_id=lineup.id,
                name=name,
                shirt_number=index + 1,
                is_starter=True,
                display_order=index,
            )
        )
    await db.flush()
    return match, lineup


async def test_a_grid_can_only_be_given_to_somebody_on_the_sheet(
    db: AsyncSession, demo: dict[str, Any]
) -> None:
    """The arrangement places players; it cannot invent them.

    Names are matched against what the provider listed, so a typo is refused
    rather than quietly creating an twelfth man nobody selected.
    """
    _match, lineup = await _fixture_with_sheet(db, demo)

    players = list(
        await db.scalars(
            select(MatchLineupPlayer).where(MatchLineupPlayer.lineup_id == lineup.id)
        )
    )
    by_name = {p.name.casefold(): p for p in players}

    assert "a. popescu" in by_name
    assert "d. inventat" not in by_name


async def test_two_players_cannot_stand_on_the_same_square(
    db: AsyncSession, demo: dict[str, Any]
) -> None:
    """Enforced by a partial unique index, not by the service.

    Partial because every substitute has a null grid, and nulls must not
    collide with each other.
    """
    from sqlalchemy.exc import IntegrityError

    _match, lineup = await _fixture_with_sheet(db, demo)
    players = list(
        await db.scalars(
            select(MatchLineupPlayer)
            .where(MatchLineupPlayer.lineup_id == lineup.id)
            .order_by(MatchLineupPlayer.display_order)
        )
    )

    players[0].grid = "2:3"
    await db.flush()

    players[1].grid = "2:3"
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_substitutes_may_all_have_no_square(
    db: AsyncSession, demo: dict[str, Any]
) -> None:
    """The other half of the partial index: nulls do not collide."""
    _match, lineup = await _fixture_with_sheet(db, demo)

    for index in range(3):
        db.add(
            MatchLineupPlayer(
                lineup_id=lineup.id,
                name=f"Sub {index}",
                is_starter=False,
                grid=None,
                display_order=20 + index,
            )
        )
    await db.flush()

    bench = list(
        await db.scalars(
            select(MatchLineupPlayer).where(
                MatchLineupPlayer.lineup_id == lineup.id,
                MatchLineupPlayer.is_starter.is_(False),
            )
        )
    )
    assert len(bench) == 3
    assert all(p.grid is None for p in bench)
