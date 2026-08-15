"""The competition pyramid, as reference data.

Romania first, but nothing here is Romania-specific: a second country is another
entry in `PYRAMIDS` and its competitions come with it. No code branches on which
country a club is in — the tier decides eligibility, and the format decides what
a round means.

Names are the competitions' own. Sponsor names are deliberately absent: they
change every few seasons and a club's archive should not say "SuperLiga Betano
2019" about a season that had a different sponsor.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import structlog
from sqlalchemy import select

from app.competitions.models import Competition, Country
from app.core.db import platform_session
from app.core.logging import configure_logging
from app.core.model_registry import *  # noqa: F403

log = structlog.get_logger("seed.competitions")


@dataclass(frozen=True, slots=True)
class CompetitionSpec:
    key: str
    name: str
    short_name: str
    format: str
    scope: str
    tier: int | None = None
    sort_order: int = 0


@dataclass(frozen=True, slots=True)
class CountrySpec:
    code: str
    name: str
    endonym: str
    competitions: list[CompetitionSpec] = field(default_factory=list)


ROMANIA = CountrySpec(
    code="RO",
    name="Romania",
    endonym="România",
    competitions=[
        CompetitionSpec("liga-1", "Liga 1", "L1", "LEAGUE", "DOMESTIC_LEAGUE", 1, 10),
        CompetitionSpec("liga-2", "Liga 2", "L2", "LEAGUE", "DOMESTIC_LEAGUE", 2, 20),
        CompetitionSpec("liga-3", "Liga 3", "L3", "LEAGUE", "DOMESTIC_LEAGUE", 3, 30),
        CompetitionSpec("liga-4", "Liga 4", "L4", "LEAGUE", "DOMESTIC_LEAGUE", 4, 40),
        CompetitionSpec("liga-5", "Liga 5", "L5", "LEAGUE", "DOMESTIC_LEAGUE", 5, 50),
        # A cup has stages, not matchdays — which is exactly why `format` is a
        # column rather than an assumption.
        CompetitionSpec(
            "cupa-romaniei", "Cupa României", "Cupa", "KNOCKOUT", "DOMESTIC_CUP", None, 60
        ),
        CompetitionSpec(
            "supercupa", "Supercupa României", "Supercupa", "KNOCKOUT", "DOMESTIC_CUP", None, 70
        ),
    ],
)

# Continental competitions belong to no country: they cut across the pyramids,
# which is why `country_id` is nullable and `tier` is not set.
EUROPE = [
    CompetitionSpec(
        "uefa-champions-league",
        "UEFA Champions League",
        "UCL",
        "GROUP_KNOCKOUT",
        "CONTINENTAL",
        None,
        100,
    ),
    CompetitionSpec(
        "uefa-europa-league",
        "UEFA Europa League",
        "UEL",
        "GROUP_KNOCKOUT",
        "CONTINENTAL",
        None,
        110,
    ),
    CompetitionSpec(
        "uefa-conference-league",
        "UEFA Conference League",
        "UECL",
        "GROUP_KNOCKOUT",
        "CONTINENTAL",
        None,
        120,
    ),
]

PYRAMIDS = [ROMANIA]


async def seed_competitions() -> None:
    """Idempotent: safe on every deploy, and updates names in place."""
    async with platform_session(reason="seed the competition pyramid", routine=True) as session:
        countries: dict[str, Country] = {
            row.code: row for row in await session.scalars(select(Country))
        }

        for spec in PYRAMIDS:
            country = countries.get(spec.code)
            if country is None:
                country = Country(code=spec.code, name=spec.name, endonym=spec.endonym)
                session.add(country)
                await session.flush()
                countries[spec.code] = country
            else:
                country.name = spec.name
                country.endonym = spec.endonym

            await _upsert(session, spec.competitions, country_id=country.id)

        # Continental competitions, with no country.
        await _upsert(session, EUROPE, country_id=None)

        total = len(EUROPE) + sum(len(c.competitions) for c in PYRAMIDS)
        log.info("competitions_seeded", countries=len(PYRAMIDS), competitions=total)


async def _upsert(session, specs: list[CompetitionSpec], *, country_id) -> None:
    existing = {
        row.key: row
        for row in await session.scalars(
            select(Competition).where(
                Competition.country_id.is_(country_id)
                if country_id is None
                else Competition.country_id == country_id
            )
        )
    }
    for spec in specs:
        competition = existing.get(spec.key)
        if competition is None:
            session.add(
                Competition(
                    country_id=country_id,
                    key=spec.key,
                    name=spec.name,
                    short_name=spec.short_name,
                    format=spec.format,
                    scope=spec.scope,
                    tier=spec.tier,
                    sort_order=spec.sort_order,
                )
            )
        else:
            competition.name = spec.name
            competition.short_name = spec.short_name
            competition.format = spec.format
            competition.scope = spec.scope
            competition.tier = spec.tier
            competition.sort_order = spec.sort_order
    await session.flush()


if __name__ == "__main__":
    configure_logging()
    asyncio.run(seed_competitions())
