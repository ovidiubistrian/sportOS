"""Connect a club to the provider's feed when it enters a competition.

The club chooses one thing it actually knows — which league it plays in — and
the feed follows from that or does not. There is no screen where somebody picks
a club out of a provider's catalogue, because that asks a question the club
cannot answer better than we can: which of four teams called "CSM" is you.

The whole design rests on being willing to fail. A wrong link puts another
club's fixtures on this club's website, and nobody notices until a match day
that does not happen. So:

  * one candidate, or nothing — two plausible matches is not a match
  * the name has to agree once folded, not merely resemble
  * no provider key, no league coverage, no answer: all fine, all the same
    outcome, which is that the club enters its own fixtures

`MANUAL` is therefore a real result and not a failure state. Most Liga III and
IV clubs will land there, and a club that can see "this division is not
covered — add your fixtures here" is better served than one staring at a
switch that quietly does nothing.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.api_football.client import ApiFootball, ProviderUnavailable
from app.integrations.models import ClubFeed

log = structlog.get_logger(__name__)

# The provider names countries in English. Only the ones the platform serves —
# an unknown code means the country cannot be used as evidence, which is no
# worse than before it was considered.
COUNTRY_NAMES = {
    "RO": "Romania",
    "MD": "Moldova",
    "GB": "England",
    "DE": "Germany",
    "FR": "France",
    "ES": "Spain",
    "IT": "Italy",
    "NL": "Netherlands",
    "PT": "Portugal",
    "PL": "Poland",
}

# Words a club's legal name carries and a provider's catalogue usually does
# not, or the other way round. Dropped from both sides before comparing, so
# "AFC Example" and "Example FC" agree.
_NOISE = {
    "fc",
    "afc",
    "cs",
    "csm",
    "cfr",
    "acs",
    "asc",
    "club",
    "sportiv",
    "municipal",
    "asociatia",
    "asociatie",
    "fotbal",
    "football",
}


def fold(name: str) -> str:
    """A name reduced to what two catalogues can be expected to agree on.

    Diacritics folded — a provider writes "Resita" where the club writes
    "Reșița" — punctuation dropped, and the boilerplate above removed. What is
    left is the part somebody would say out loud.
    """
    decomposed = unicodedata.normalize("NFKD", name or "")
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    words = re.split(r"[^a-z0-9]+", ascii_only.lower())
    # Single letters go too. `F.C. Voluntari` splits into `f`, `c`,
    # `voluntari`, and a lone letter is never the part of a name that
    # distinguishes one club from another.
    kept = [word for word in words if len(word) > 1 and word not in _NOISE]
    return " ".join(kept)


@dataclass(frozen=True, slots=True)
class LinkResult:
    linked: bool
    reason: str
    """Short, and meant to be shown: the club reads this."""

    provider_team_id: str | None = None
    provider_team_name: str | None = None


def season_year(season_name: str) -> int | None:
    """`2025/26` → 2025. The provider numbers a season by the year it starts."""
    match = re.match(r"\s*(\d{4})", season_name or "")
    return int(match.group(1)) if match else None


async def try_link(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    club_id: UUID,
    club_name: str,
    season_name: str,
    country_code: str | None = None,
) -> LinkResult:
    """Look for this club in the provider's catalogue, and link it if certain.

    Never raises. Entering a competition is the club's action and must succeed
    whether or not a third party is reachable — the feed is an enhancement to
    it, not a precondition.
    """
    if not settings.api_football_key:
        return LinkResult(False, "The platform has no results feed configured.")

    year = season_year(season_name)
    if year is None:
        return LinkResult(False, f"Cannot tell which year {season_name!r} starts in.")

    wanted = fold(club_name)
    if not wanted:
        return LinkResult(False, "The club's name has nothing to match on.")

    try:
        async with ApiFootball() as client:
            rows = await client.search_teams(query=club_name)
    except ProviderUnavailable as exc:
        log.info("autolink_provider_unavailable", club_id=str(club_id), error=str(exc))
        return LinkResult(
            False, "The results feed did not answer. You can add fixtures yourself."
        )
    except Exception:
        log.exception("autolink_search_failed", club_id=str(club_id))
        return LinkResult(False, "The results feed could not be reached.")

    named = [
        row["team"]
        for row in rows
        if row.get("team") and fold(row["team"].get("name") or "") == wanted
    ]

    # A name alone is one fact, and clubs share names across borders: there is
    # a "Dinamo" in half of Europe. The country is a second fact, free in the
    # same response, and it is what makes a single remaining candidate mean
    # something rather than merely being the only one we happened to see.
    country = COUNTRY_NAMES.get((country_code or "").upper())
    candidates = (
        [team for team in named if (team.get("country") or "").lower() == country.lower()]
        if country
        else named
    )
    if named and not candidates:
        log.info(
            "autolink_wrong_country",
            club_id=str(club_id),
            expected=country,
            found=[team.get("country") for team in named],
        )
        return LinkResult(
            False, f"The only club with this name in the feed is not in {country}."
        )

    if not candidates:
        return LinkResult(
            False,
            "This club is not in the results feed. Add your fixtures and results yourself.",
        )
    if len(candidates) > 1:
        # Two teams with the same folded name — reserves, a women's side, or a
        # namesake in another county. Guessing here is how another club's
        # season ends up on this one's website.
        log.info(
            "autolink_ambiguous",
            club_id=str(club_id),
            matches=[team.get("name") for team in candidates],
        )
        return LinkResult(
            False,
            "More than one club in the feed has this name, so nothing was connected.",
        )

    team = candidates[0]
    provider_id = str(team["id"])

    feed = await session.scalar(
        select(ClubFeed).where(ClubFeed.club_id == club_id, ClubFeed.provider == "API_FOOTBALL")
    )
    if feed is None:
        feed = ClubFeed(tenant_id=tenant_id, club_id=club_id, provider="API_FOOTBALL")
        session.add(feed)

    feed.mode = "AUTO"
    feed.provider_team_id = provider_id
    feed.provider_team_name = team.get("name")
    feed.season_year = year
    feed.last_error = None
    # Due immediately: the club has just told us its league and expects to see
    # its fixtures, not to find out tomorrow whether this worked.
    feed.last_fixtures_at = None
    feed.last_standings_at = None
    await session.flush()

    log.info(
        "autolink_connected",
        club_id=str(club_id),
        provider_team_id=provider_id,
        provider_team_name=team.get("name"),
        season=year,
    )
    return LinkResult(
        True,
        f"Connected to {team.get('name')} in the results feed. Fixtures arrive shortly.",
        provider_team_id=provider_id,
        provider_team_name=team.get("name"),
    )


def stale(feed: ClubFeed | None) -> bool:
    """Whether a linked feed has never actually fetched anything.

    Used by the admin to distinguish "connected, waiting for the first sync"
    from "connected and working", which look the same from the database and
    very different to somebody who has just pressed a button.
    """
    return feed is not None and feed.mode == "AUTO" and feed.last_fixtures_at is None


def since(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    return f"{int((datetime.now(UTC) - moment).total_seconds() // 60)} minutes ago"
