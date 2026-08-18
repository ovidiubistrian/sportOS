"""Pulling fixtures, results, standings, squads and live scores.

The rule, decided once and applied everywhere in this file: **once a club links
a season to API-Football, the provider owns those fixtures.** Sync writes them,
the club cannot edit them, and the club keeps entering everything the provider
does not cover — friendlies, youth games, anything below the provider's
coverage. One writer per row is the only version of this that stays correct;
"merge on conflict" means the next sync quietly reverts a correction somebody
made on purpose.

Everything here runs on `platform_session`. Competitions, the club directory
and fixtures are platform reference data shared between tenants — a Liga 2
fixture belongs to both clubs playing it, and neither owns the row.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.competitions.models import (
    ClubSeasonRecord,
    Competition,
    CompetitionEntry,
    CompetitionSeason,
    DirectoryClub,
    Match,
    MatchEvent,
    MatchLineup,
    MatchLineupPlayer,
)
from app.core.ids import new_id
from app.identity.registration import slugify
from app.integrations.api_football.client import (
    PROVIDER,
    ApiFootball,
    ProviderUnavailable,
)
from app.integrations.models import ProviderLink

log = structlog.get_logger(__name__)

# The provider's status codes, mapped onto ours. Anything unlisted is treated
# as scheduled: an unknown code is not a reason to blank a fixture.
STATUS_MAP = {
    "TBD": "SCHEDULED",
    "NS": "SCHEDULED",
    "1H": "LIVE",
    "HT": "LIVE",
    "2H": "LIVE",
    "ET": "LIVE",
    "BT": "LIVE",
    "P": "LIVE",
    "LIVE": "LIVE",
    "FT": "FINISHED",
    "AET": "FINISHED",
    "PEN": "FINISHED",
    "PST": "POSTPONED",
    "CANC": "CANCELLED",
    "ABD": "CANCELLED",
    "AWD": "AWARDED",
    "WO": "AWARDED",
}

LIVE_STATUSES = {"1H", "HT", "2H", "ET", "BT", "P", "LIVE"}


def parse_round(raw: str | None) -> tuple[str, int | None, str | None]:
    """The provider's round string, as structure rather than prose.

    It sends "Regular Season - 3" and "Final". Storing those verbatim means the
    site shows English mid-sentence on a Romanian page and cannot sort by
    matchday. A league round becomes a number the interface can label in the
    reader's own language; a cup round keeps its name, because "Semi-finals"
    is a name and not a number.
    """
    if not raw:
        return "MATCHDAY", None, None

    text = raw.strip()
    lowered = text.lower()
    if lowered.startswith("regular season"):
        digits = "".join(ch for ch in text if ch.isdigit())
        return "MATCHDAY", int(digits) if digits else None, None
    if lowered.startswith("group"):
        return "GROUP", None, text
    return "STAGE", None, text


@dataclass(slots=True)
class SyncResult:
    created: int = 0
    updated: int = 0
    requests: int = 0
    remaining: int | None = None


async def _link(session: AsyncSession, entity: str, provider_id: str) -> ProviderLink | None:
    return await session.scalar(
        select(ProviderLink).where(
            ProviderLink.provider == PROVIDER,
            ProviderLink.entity_type == entity,
            ProviderLink.provider_id == str(provider_id),
        )
    )


async def _remember(
    session: AsyncSession,
    entity: str,
    provider_id: str,
    local_id: UUID,
    snapshot: dict[str, Any] | None = None,
) -> ProviderLink:
    """Upsert the mapping, from either direction.

    A local row holds exactly one provider identity and vice versa — both
    unique constraints say so. So the lookup has to be by *both* keys: finding
    only by provider id means a club that already carries a different one
    fails on insert instead of being corrected, which is what happened the
    first time a real team id met a row a test had linked to a made-up one.
    """
    link = await _link(session, entity, provider_id)
    if link is None:
        link = await session.scalar(
            select(ProviderLink).where(
                ProviderLink.provider == PROVIDER,
                ProviderLink.entity_type == entity,
                ProviderLink.local_id == local_id,
            )
        )
        if link is not None and link.provider_id != str(provider_id):
            log.info(
                "provider_link_rebound",
                entity=entity,
                local_id=str(local_id),
                was=link.provider_id,
                now=str(provider_id),
            )
    if link is None:
        link = ProviderLink(
            id=new_id(),
            provider=PROVIDER,
            entity_type=entity,
            local_id=local_id,
            provider_id=str(provider_id),
        )
        session.add(link)
    link.local_id = local_id
    link.provider_id = str(provider_id)
    link.snapshot = snapshot or {}
    link.synced_at = datetime.now(UTC)
    await session.flush()
    return link


async def ensure_club(session: AsyncSession, team: dict[str, Any]) -> DirectoryClub:
    """Find or create the directory row for a provider team.

    Matched by provider id first and by slug second. The slug fallback is what
    adopts the clubs a league already entered by hand — without it, linking a
    season would create a second "Concordia Chiajna" and split the table in two.
    """
    provider_id = str(team.get("id"))
    name = (team.get("name") or "").strip()

    link = await _link(session, "DIRECTORY_CLUB", provider_id)
    if link is not None:
        club = await session.get(DirectoryClub, link.local_id)
        if club is not None:
            club.name = name or club.name
            if team.get("logo"):
                club.crest_url = team["logo"]
            await _remember(session, "DIRECTORY_CLUB", provider_id, club.id, team)
            return club

    slug = slugify(name)
    club = await session.scalar(select(DirectoryClub).where(DirectoryClub.slug == slug))
    if club is None:
        club = DirectoryClub(
            slug=slug,
            name=name,
            short_name=(team.get("code") or "".join(w[0] for w in name.split()[:3]))[
                :16
            ].upper(),
            city=None,
        )
        session.add(club)
        await session.flush()

    if team.get("logo"):
        # The club's own uploaded crest wins; this fills the gap for the
        # opponents nobody on the platform has set up.
        club.crest_url = club.crest_url or team["logo"]

    await _remember(session, "DIRECTORY_CLUB", provider_id, club.id, team)
    return club


def _kickoff(fixture: dict[str, Any]) -> datetime | None:
    raw = (fixture.get("fixture") or {}).get("date")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


async def sync_fixtures(
    session: AsyncSession,
    client: ApiFootball,
    *,
    season: CompetitionSeason,
    provider_league: str,
    provider_season: int,
) -> SyncResult:
    """Fixtures and results for one linked season.

    Also enters both clubs into the season, for the same reason the manual
    route does: a table computed from results skips any match whose clubs are
    not entrants, so a synced fixture list with no entries produces an empty
    league table and a confusing support ticket.
    """
    result = SyncResult()
    payload = await client.fixtures(league=provider_league, season=provider_season)

    for item in payload:
        await _write_fixture(session, item, season, result)

    result.requests = client.usage.requests
    result.remaining = client.usage.remaining
    return result


async def _write_fixture(
    session: AsyncSession,
    item: dict[str, Any],
    season: CompetitionSeason,
    result: SyncResult,
) -> None:
    """One provider fixture, written into our model."""
    fixture = item.get("fixture") or {}
    teams = item.get("teams") or {}
    goals = item.get("goals") or {}
    league = item.get("league") or {}

    home = await ensure_club(session, teams.get("home") or {})
    away = await ensure_club(session, teams.get("away") or {})
    await _ensure_entered(session, season.id, home.id, away.id)

    provider_status = ((fixture.get("status") or {}).get("short") or "NS").upper()
    status = STATUS_MAP.get(provider_status, "SCHEDULED")
    # A kicked-off match has a score even before anybody scores; the
    # provider sometimes sends null for it, and the database requires the
    # pair to agree with the status.
    scored = status in ("FINISHED", "AWARDED", "LIVE")

    link = await _link(session, "MATCH", str(fixture.get("id")))
    match = await session.get(Match, link.local_id) if link else None

    if match is None:
        # Adopt a fixture the club already entered by hand, rather than
        # adding a second copy of it. Without this, linking a season that
        # a club has been keeping manually doubles every match in it — and
        # the league table counts both.
        match = await _adopt(session, season.id, home.id, away.id, _kickoff(item))
        if match is not None:
            result.updated += 1

    if match is None:
        match = Match(
            competition_season_id=season.id,
            home_club_id=home.id,
            away_club_id=away.id,
            round_kind="MATCHDAY",
            status="SCHEDULED",
            source=PROVIDER,
        )
        session.add(match)
        await session.flush()
        result.created += 1
    else:
        result.updated += 1

    match.home_club_id = home.id
    match.away_club_id = away.id
    match.kickoff_at = _kickoff(item)
    match.kickoff_is_confirmed = provider_status != "TBD"
    match.venue_name = (fixture.get("venue") or {}).get("name")
    round_kind, round_number, round_label = parse_round(league.get("round"))
    match.round_kind = round_kind
    match.round_number = round_number
    match.round_label = round_label
    match.status = status
    # The two must agree — the database enforces it — so a status without
    # a score, or the reverse, is normalised here rather than at the
    # constraint, which cannot explain itself.
    match.home_score = (goals.get("home") or 0) if scored else None
    match.away_score = (goals.get("away") or 0) if scored else None
    match.minute = (
        (fixture.get("status") or {}).get("elapsed")
        if provider_status in LIVE_STATUSES
        else None
    )
    match.source = PROVIDER

    await _remember(session, "MATCH", str(fixture.get("id")), match.id, item)


async def _adopt(
    session: AsyncSession,
    season_id: UUID,
    home_id: UUID,
    away_id: UUID,
    kickoff: datetime | None,
) -> Match | None:
    """An unlinked fixture between the same two clubs, near the same date.

    Matched on the pairing rather than the kick-off alone, because a club that
    entered a fixture by hand usually had the date roughly right and the time
    wrong — which is exactly what the feed is for. A week either side is wide
    enough for a postponement and narrow enough not to swallow the reverse
    fixture, which is months away.
    """
    stmt = select(Match).where(
        Match.competition_season_id == season_id,
        Match.home_club_id == home_id,
        Match.away_club_id == away_id,
        Match.source == "CLUB",
    )
    for candidate in await session.scalars(stmt):
        if kickoff is None or candidate.kickoff_at is None:
            return candidate
        if abs((candidate.kickoff_at - kickoff).days) <= 7:
            return candidate
    return None


async def _ensure_entered(session: AsyncSession, season_id: UUID, *club_ids: UUID) -> None:
    present = set(
        await session.scalars(
            select(CompetitionEntry.directory_club_id).where(
                CompetitionEntry.competition_season_id == season_id,
                CompetitionEntry.directory_club_id.in_(club_ids),
            )
        )
    )
    for club_id in club_ids:
        if club_id not in present:
            session.add(
                CompetitionEntry(competition_season_id=season_id, directory_club_id=club_id)
            )
    await session.flush()


async def sync_live(
    session: AsyncSession, client: ApiFootball, *, season: CompetitionSeason
) -> SyncResult:
    """Refresh only the matches that are actually on.

    Deliberately not the provider's `live=all`: on a Saturday that returns
    every game on the planet and spends a shared allowance on clubs nobody
    here supports. The candidates are our own kicked-off-and-not-finished
    fixtures, looked up by id.
    """
    result = SyncResult()
    now = datetime.now(UTC)

    candidates = list(
        await session.scalars(
            select(Match).where(
                Match.competition_season_id == season.id,
                Match.source == PROVIDER,
                Match.status.in_(("SCHEDULED", "LIVE")),
                Match.kickoff_at.isnot(None),
                Match.kickoff_at <= now,
            )
        )
    )
    if not candidates:
        return result

    by_provider: dict[str, Match] = {}
    for match in candidates:
        link = await session.scalar(
            select(ProviderLink).where(
                ProviderLink.provider == PROVIDER,
                ProviderLink.entity_type == "MATCH",
                ProviderLink.local_id == match.id,
            )
        )
        if link is not None:
            by_provider[link.provider_id] = match

    for item in await client.live_fixtures(ids=list(by_provider)):
        fixture = item.get("fixture") or {}
        match = by_provider.get(str(fixture.get("id")))
        if match is None:
            continue

        goals = item.get("goals") or {}
        provider_status = ((fixture.get("status") or {}).get("short") or "NS").upper()
        status = STATUS_MAP.get(provider_status, match.status)
        scored = status in ("FINISHED", "AWARDED", "LIVE")

        match.status = status
        match.home_score = (goals.get("home") or 0) if scored else None
        match.away_score = (goals.get("away") or 0) if scored else None
        match.minute = (
            (fixture.get("status") or {}).get("elapsed")
            if provider_status in LIVE_STATUSES
            else None
        )
        result.updated += 1

    result.requests = client.usage.requests
    result.remaining = client.usage.remaining
    return result


# --- syncing one club, across every competition it plays in -----------------


async def ensure_competition_season(
    session: AsyncSession, league: dict[str, Any], client: ApiFootball | None = None
) -> CompetitionSeason:
    """The competition and season a provider fixture belongs to.

    Created on sight rather than requiring a curator to map every cup first.
    Competitions are platform reference data, and a fixture arriving for one we
    have never heard of is not a reason to drop the fixture — a club in the cup
    would simply lose half its calendar. A curated competition already linked
    is found and reused; a new one is created and linked.
    """
    provider_league = str(league.get("id"))
    link = await _link(session, "COMPETITION", provider_league)

    competition = await session.get(Competition, link.local_id) if link is not None else None
    if competition is None:
        name = (league.get("name") or "").strip()
        key = slugify(name) or f"provider-{provider_league}"
        competition = await session.scalar(select(Competition).where(Competition.key == key))
        if competition is None:
            # A fixture's league object carries no `type`, so asking the
            # catalogue is the only way to know whether this is a division, a
            # cup or a set of friendlies. One call the first time a
            # competition is seen, never again — and getting it wrong files
            # friendlies as a league and puts them in the table.
            kind = (league.get("type") or "").lower()
            if not kind and client is not None:
                try:
                    found = await client.get("/leagues", id=provider_league)
                    kind = ((found[0]["league"].get("type") if found else "") or "").lower()
                except ProviderUnavailable:
                    kind = ""
            is_cup = kind != "league"
            competition = Competition(
                key=key,
                name=name,
                short_name=name[:16],
                format="KNOCKOUT" if is_cup else "LEAGUE",
                scope="DOMESTIC_CUP" if is_cup else "DOMESTIC_LEAGUE",
                # A league needs a tier and the provider does not give one.
                # Bottom of the pyramid is wrong less often than top, and a
                # curator can correct it in the console.
                tier=None if is_cup else 9,
                sort_order=500,
                is_active=True,
            )
            session.add(competition)
            await session.flush()
        await _remember(session, "COMPETITION", provider_league, competition.id, league)

    year = league.get("season")
    season_name = f"{year}/{str(int(year) + 1)[2:]}" if year else "—"
    season_key = f"{provider_league}:{year}"

    season_link = await _link(session, "COMPETITION_SEASON", season_key)
    season = (
        await session.get(CompetitionSeason, season_link.local_id)
        if season_link is not None
        else None
    )
    if season is None:
        season = await session.scalar(
            select(CompetitionSeason).where(
                CompetitionSeason.competition_id == competition.id,
                CompetitionSeason.name == season_name,
            )
        )
    if season is None:
        season = CompetitionSeason(
            competition_id=competition.id,
            name=season_name,
            start_date=date(int(year), 7, 1),
            end_date=date(int(year) + 1, 6, 30),
            is_current=True,
        )
        session.add(season)
        await session.flush()

    await _remember(
        session,
        "COMPETITION_SEASON",
        season_key,
        season.id,
        {"league": provider_league, "season": year},
    )
    return season


async def sync_club_fixtures(
    session: AsyncSession,
    client: ApiFootball,
    *,
    provider_team_id: str,
    season_year: int,
) -> SyncResult:
    """Everything one club plays this season, in a single call.

    By team rather than by league: a club's calendar spans its division, the
    national cup and sometimes Europe, and one call returns all three. Syncing
    by league would be one call per competition and would still miss the cup
    the club has not been drawn into yet.
    """
    result = SyncResult()
    payload = await client.fixtures_for_team(team=provider_team_id, season=season_year)

    for item in payload:
        league = item.get("league") or {}
        if not league.get("id"):
            continue
        season = await ensure_competition_season(session, league, client)
        await _write_fixture(session, item, season, result)

    result.requests = client.usage.requests
    result.remaining = client.usage.remaining
    return result


async def sync_standings(
    session: AsyncSession,
    client: ApiFootball,
    *,
    provider_league: str,
    provider_season: int,
) -> SyncResult:
    """The whole division's table, as the competition publishes it.

    Every club's row, not just ours. Our own table is computed from results,
    which is right when the club enters its own fixtures — but a club on the
    feed only syncs *its* matches, so computing would show it on nine points
    and every other side on nil. The provider knows what the other twenty-one
    did last Saturday and we do not.
    """
    result = SyncResult()
    payload = await client.standings(league=provider_league, season=provider_season)
    if not payload:
        result.requests = client.usage.requests
        return result

    season_key = f"{provider_league}:{provider_season}"
    link = await _link(session, "COMPETITION_SEASON", season_key)
    if link is None:
        result.requests = client.usage.requests
        return result

    groups = ((payload[0].get("league") or {}).get("standings")) or []
    for group in groups:
        for row in group:
            team = row.get("team") or {}
            club = await ensure_club(session, team)
            stats = row.get("all") or {}
            goals = stats.get("goals") or {}

            entry = await session.scalar(
                select(CompetitionEntry).where(
                    CompetitionEntry.competition_season_id == link.local_id,
                    CompetitionEntry.directory_club_id == club.id,
                )
            )
            if entry is None:
                entry = CompetitionEntry(
                    competition_season_id=link.local_id, directory_club_id=club.id
                )
                session.add(entry)
            entry.group_label = row.get("group")

            record = await session.scalar(
                select(ClubSeasonRecord).where(
                    ClubSeasonRecord.directory_club_id == club.id,
                    ClubSeasonRecord.competition_season_id == link.local_id,
                )
            )
            if record is None:
                record = ClubSeasonRecord(
                    directory_club_id=club.id, competition_season_id=link.local_id
                )
                session.add(record)
                result.created += 1
            else:
                result.updated += 1

            record.position = row.get("rank")
            record.played = stats.get("played") or 0
            record.won = stats.get("win") or 0
            record.drawn = stats.get("draw") or 0
            record.lost = stats.get("lose") or 0
            record.goals_for = goals.get("for") or 0
            record.goals_against = goals.get("against") or 0
            record.points = row.get("points") or 0
            record.form = row.get("form")
            record.outcome = row.get("description")
            stamped = row.get("update")
            if stamped:
                with contextlib.suppress(ValueError):
                    record.published_at = datetime.fromisoformat(stamped.replace("Z", "+00:00"))

    await session.flush()
    result.requests = client.usage.requests
    result.remaining = client.usage.remaining
    return result


async def leagues_played(session: AsyncSession, *, provider_team_id: str) -> list[str]:
    """The provider league ids this club has fixtures in.

    Read from what the fixtures sync just wrote rather than from the
    catalogue, so a cup the club was drawn into yesterday is included and the
    twelve competitions it is not in cost nothing.
    """
    club_link = await session.scalar(
        select(ProviderLink).where(
            ProviderLink.provider == PROVIDER,
            ProviderLink.entity_type == "DIRECTORY_CLUB",
            ProviderLink.provider_id == str(provider_team_id),
        )
    )
    if club_link is None:
        return []

    season_ids = set(
        await session.scalars(
            select(Match.competition_season_id).where(
                or_(
                    Match.home_club_id == club_link.local_id,
                    Match.away_club_id == club_link.local_id,
                ),
                Match.source == PROVIDER,
            )
        )
    )
    if not season_ids:
        return []

    # Only leagues: a cup and a set of friendlies have no table, and asking
    # for one spends a call from the shared allowance to be told nothing.
    rows = (
        await session.execute(
            select(ProviderLink.provider_id)
            .join(
                CompetitionSeason,
                CompetitionSeason.id == ProviderLink.local_id,
            )
            .join(Competition, Competition.id == CompetitionSeason.competition_id)
            .where(
                ProviderLink.provider == PROVIDER,
                ProviderLink.entity_type == "COMPETITION_SEASON",
                ProviderLink.local_id.in_(season_ids),
                Competition.format == "LEAGUE",
            )
        )
    ).all()
    # The season link's key is "<league>:<year>".
    return sorted({row[0].split(":")[0] for row in rows})


async def sync_live_for_club(
    session: AsyncSession, client: ApiFootball, *, provider_team_id: str
) -> SyncResult:
    """Refresh whichever of this club's matches are actually being played.

    Looked up by fixture id rather than the provider's `live=all`, which on a
    Saturday returns every match in the world and spends the allowance on
    clubs nobody here supports.
    """
    result = SyncResult()

    club_link = await session.scalar(
        select(ProviderLink).where(
            ProviderLink.provider == PROVIDER,
            ProviderLink.entity_type == "DIRECTORY_CLUB",
            ProviderLink.provider_id == str(provider_team_id),
        )
    )
    if club_link is None:
        return result

    now = datetime.now(UTC)
    candidates = list(
        await session.scalars(
            select(Match).where(
                or_(
                    Match.home_club_id == club_link.local_id,
                    Match.away_club_id == club_link.local_id,
                ),
                Match.source == PROVIDER,
                Match.status.in_(("SCHEDULED", "LIVE")),
                Match.kickoff_at.isnot(None),
                Match.kickoff_at <= now,
            )
        )
    )
    if not candidates:
        return result

    by_provider: dict[str, Match] = {}
    for match in candidates:
        link = await session.scalar(
            select(ProviderLink).where(
                ProviderLink.provider == PROVIDER,
                ProviderLink.entity_type == "MATCH",
                ProviderLink.local_id == match.id,
            )
        )
        if link is not None:
            by_provider[link.provider_id] = match

    for item in await client.live_fixtures(ids=list(by_provider)):
        fixture = item.get("fixture") or {}
        match = by_provider.get(str(fixture.get("id")))
        if match is None:
            continue

        goals = item.get("goals") or {}
        provider_status = ((fixture.get("status") or {}).get("short") or "NS").upper()
        status = STATUS_MAP.get(provider_status, match.status)
        scored = status in ("FINISHED", "AWARDED", "LIVE")

        match.status = status
        match.home_score = (goals.get("home") or 0) if scored else None
        match.away_score = (goals.get("away") or 0) if scored else None
        match.minute = (
            (fixture.get("status") or {}).get("elapsed")
            if provider_status in LIVE_STATUSES
            else None
        )
        result.updated += 1

    await session.flush()
    result.requests = client.usage.requests
    result.remaining = client.usage.remaining
    return result


# The provider's event vocabulary, reduced to the four things a supporter reads
# in a match report. Anything unrecognised is dropped rather than shown raw.
EVENT_KIND_MAP = {
    "goal": "GOAL",
    "card": "CARD",
    "subst": "SUBSTITUTION",
    "var": "VAR",
}


async def sync_match_events(
    session: AsyncSession,
    client: ApiFootball,
    *,
    match: Match,
    payload: list[dict[str, Any]] | None = None,
) -> SyncResult:
    """Goals, cards and substitutions for one match.

    One call per match, and only for matches worth spending it on: a fixture
    that has not kicked off has no events, and one whose events we already
    hold does not change once the referee has gone home.

    `payload` skips the call entirely. A single `/fixtures?id=` response
    carries the score, the events *and* the team sheets, so during a live match
    one request feeds everything — see `sync_live_snapshot_for_club`.
    """
    result = SyncResult()

    link = await session.scalar(
        select(ProviderLink).where(
            ProviderLink.provider == PROVIDER,
            ProviderLink.entity_type == "MATCH",
            ProviderLink.local_id == match.id,
        )
    )
    if link is None:
        return result

    if payload is None:
        payload = await client.get("/fixtures/events", fixture=link.provider_id)

    existing = {
        (e.minute, e.kind, e.player_name): e
        for e in await session.scalars(
            select(MatchEvent).where(MatchEvent.match_id == match.id)
        )
    }

    for item in payload:
        kind = EVENT_KIND_MAP.get((item.get("type") or "").strip().lower())
        if kind is None:
            continue

        time = item.get("time") or {}
        player = (item.get("player") or {}).get("name")
        team = item.get("team") or {}

        club = await ensure_club(session, team) if team.get("id") else None
        key = (time.get("elapsed"), kind, player)

        event = existing.get(key)
        if event is None:
            event = MatchEvent(match_id=match.id, minute=time.get("elapsed"), kind=kind)
            session.add(event)
            result.created += 1
        else:
            result.updated += 1

        event.club_id = club.id if club else None
        event.extra_minute = time.get("extra")
        event.detail = item.get("detail")
        event.player_name = player
        event.related_name = (item.get("assist") or {}).get("name")
        event.comment = item.get("comments")

    await session.flush()
    result.requests = client.usage.requests
    result.remaining = client.usage.remaining
    return result


async def sync_events_for_club(
    session: AsyncSession, client: ApiFootball, *, provider_team_id: str, limit: int = 6
) -> SyncResult:
    """Events for this club's live matches and its recently finished ones.

    Bounded, because a season is twenty games and re-reading all of them every
    night would spend twenty calls to learn nothing. A finished match is
    fetched once; a live one is refreshed while it is on.
    """
    total = SyncResult()

    club_link = await session.scalar(
        select(ProviderLink).where(
            ProviderLink.provider == PROVIDER,
            ProviderLink.entity_type == "DIRECTORY_CLUB",
            ProviderLink.provider_id == str(provider_team_id),
        )
    )
    if club_link is None:
        return total

    played = list(
        await session.scalars(
            select(Match)
            .where(
                or_(
                    Match.home_club_id == club_link.local_id,
                    Match.away_club_id == club_link.local_id,
                ),
                Match.source == PROVIDER,
                Match.status.in_(("LIVE", "FINISHED", "AWARDED")),
            )
            .order_by(Match.kickoff_at.desc())
            .limit(limit)
        )
    )

    for match in played:
        has_events = await session.scalar(
            select(MatchEvent.id).where(MatchEvent.match_id == match.id).limit(1)
        )
        # A finished match we already have is settled; a live one is not.
        if has_events is not None and match.status != "LIVE":
            continue
        one = await sync_match_events(session, client, match=match)
        total.created += one.created
        total.updated += one.updated

    total.requests = client.usage.requests
    total.remaining = client.usage.remaining
    return total


async def sync_club_profile(
    session: AsyncSession, client: ApiFootball, *, provider_team_id: str
) -> SyncResult:
    """Founding year, ground and capacity — the club's own facts.

    One call, rarely repeated: a stadium's capacity changes when it is rebuilt,
    not weekly.
    """
    result = SyncResult()
    rows = await client.get("/teams", id=provider_team_id)
    if not rows:
        return result

    team = rows[0].get("team") or {}
    venue = rows[0].get("venue") or {}
    club = await ensure_club(session, team)

    club.founded_year = team.get("founded")
    club.city = venue.get("city") or club.city
    club.venue_name = venue.get("name")
    club.venue_capacity = venue.get("capacity")
    result.updated += 1

    await session.flush()
    result.requests = client.usage.requests
    result.remaining = client.usage.remaining
    return result


async def sync_club_history(
    session: AsyncSession,
    client: ApiFootball,
    *,
    provider_team_id: str,
    max_seasons: int = 12,
) -> SyncResult:
    """Where the club finished, season by season.

    One call to learn which competitions and seasons it has played, then one
    per league season for the table. Cups are skipped: they have no standings,
    and asking spends a call to be told so.

    Bounded to the most recent seasons. A club's whole record is interesting;
    it is not interesting enough to spend forty calls on every night, and the
    older seasons never change once fetched.
    """
    result = SyncResult()
    catalogue = await client.get("/leagues", team=provider_team_id)

    wanted: list[tuple[dict[str, Any], int]] = []
    for row in catalogue:
        league = row.get("league") or {}
        if (league.get("type") or "").lower() != "league":
            continue
        for season in row.get("seasons") or []:
            year = season.get("year")
            if year is not None:
                wanted.append((league, int(year)))

    wanted.sort(key=lambda pair: pair[1], reverse=True)

    for league, year in wanted[:max_seasons]:
        season = await ensure_competition_season(session, {**league, "season": year}, client)
        link = await _link(session, "COMPETITION_SEASON", f"{league['id']}:{year}")
        if link is None:
            continue

        # Skip a season already recorded: a finished table is a fact.
        club_link = await _link(session, "DIRECTORY_CLUB", str(provider_team_id))
        if club_link is not None:
            known = await session.scalar(
                select(ClubSeasonRecord).where(
                    ClubSeasonRecord.directory_club_id == club_link.local_id,
                    ClubSeasonRecord.competition_season_id == season.id,
                )
            )
            if known is not None and known.played > 0 and year < max(y for _, y in wanted):
                continue

        try:
            payload = await client.standings(league=str(league["id"]), season=year)
        except ProviderUnavailable:
            continue

        for group in (
            ((payload[0].get("league") or {}).get("standings") or []) if payload else []
        ):
            for entry in group:
                team = entry.get("team") or {}
                if str(team.get("id")) != str(provider_team_id):
                    continue
                club = await ensure_club(session, team)
                stats = entry.get("all") or {}
                goals = stats.get("goals") or {}

                record = await session.scalar(
                    select(ClubSeasonRecord).where(
                        ClubSeasonRecord.directory_club_id == club.id,
                        ClubSeasonRecord.competition_season_id == season.id,
                    )
                )
                if record is None:
                    record = ClubSeasonRecord(
                        directory_club_id=club.id, competition_season_id=season.id
                    )
                    session.add(record)
                    result.created += 1
                else:
                    result.updated += 1

                record.position = entry.get("rank")
                record.played = stats.get("played") or 0
                record.won = stats.get("win") or 0
                record.drawn = stats.get("draw") or 0
                record.lost = stats.get("lose") or 0
                record.goals_for = goals.get("for") or 0
                record.goals_against = goals.get("against") or 0
                record.points = entry.get("points") or 0
                record.outcome = entry.get("description")

    await session.flush()
    result.requests = client.usage.requests
    result.remaining = client.usage.remaining
    return result


async def sync_league_fixtures(
    session: AsyncSession,
    client: ApiFootball,
    *,
    provider_league: str,
    provider_season: int,
) -> SyncResult:
    """Every fixture in a division, so the table can be kept honest.

    One call for the whole season. Without it we hold only the fixtures of the
    club that connected the feed, and a table adjusted with those alone would
    show that club a round ahead of twenty-one others — more wrong than the
    stale table it was trying to correct.
    """
    result = SyncResult()
    payload = await client.fixtures(league=provider_league, season=provider_season)

    for item in payload:
        league = item.get("league") or {}
        if not league.get("id"):
            continue
        season = await ensure_competition_season(session, league, client)
        await _write_fixture(session, item, season, result)

    result.requests = client.usage.requests
    result.remaining = client.usage.remaining
    return result


def _shirt_number(raw: Any) -> int | None:
    try:
        number = int(raw)
    except (TypeError, ValueError):
        return None
    return number if 0 < number < 200 else None


async def sync_match_lineups(
    session: AsyncSession,
    client: ApiFootball,
    *,
    match: Match,
    payload: list[dict[str, Any]] | None = None,
) -> SyncResult:
    """Both team sheets for one match.

    **What arrives depends on the league.** Every league the provider carries
    gives names and shirt numbers; only the ones it covers fully give
    `formation`, `pos` and `grid`. For the Romanian second division those three
    come back null, which is why they are nullable here and why a club that
    wants a pitch rather than a list arranges the eleven itself.

    A lineup a club has arranged is not flattened by a later sync. Names and
    substitutes are refreshed — a late change to the bench should show — but
    the shape somebody set that morning is left exactly where they put it.
    """
    result = SyncResult()

    if payload is None:
        provider_link = await session.scalar(
            select(ProviderLink).where(
                ProviderLink.provider == PROVIDER,
                ProviderLink.entity_type == "MATCH",
                ProviderLink.local_id == match.id,
            )
        )
        if provider_link is None:
            return result
        payload = await client.lineups(fixture=provider_link.provider_id)
    if not payload:
        return result

    for entry in payload:
        team = entry.get("team") or {}
        team_id = str(team.get("id") or "")
        club_link = await session.scalar(
            select(ProviderLink).where(
                ProviderLink.provider == PROVIDER,
                ProviderLink.entity_type == "DIRECTORY_CLUB",
                ProviderLink.provider_id == team_id,
            )
        )
        if club_link is None:
            continue

        if club_link.local_id == match.home_club_id:
            side = "HOME"
        elif club_link.local_id == match.away_club_id:
            side = "AWAY"
        else:
            continue

        lineup = await session.scalar(
            select(MatchLineup).where(
                MatchLineup.match_id == match.id, MatchLineup.side == side
            )
        )
        if lineup is None:
            lineup = MatchLineup(match_id=match.id, side=side)
            session.add(lineup)
            await session.flush()
            result.created += 1
        else:
            result.updated += 1

        arranged = lineup.source == "CLUB"
        coach = (entry.get("coach") or {}).get("name")
        if coach:
            lineup.coach_name = coach
        # Only taken when the provider actually has one. Overwriting a club's
        # chosen shape with null is how an arranged pitch becomes a list again.
        if entry.get("formation") and not arranged:
            lineup.formation = entry["formation"]

        # Positions are rebuilt wholesale, because a team sheet is a set and a
        # diff against names is guesswork. A club's arrangement survives
        # because the grid is carried over by name below.
        existing_grid: dict[str, str] = {}
        if arranged:
            for row in await session.scalars(
                select(MatchLineupPlayer).where(MatchLineupPlayer.lineup_id == lineup.id)
            ):
                if row.grid:
                    existing_grid[row.name.casefold()] = row.grid

        await session.execute(
            delete(MatchLineupPlayer).where(MatchLineupPlayer.lineup_id == lineup.id)
        )

        for starter, group in (("startXI", True), ("substitutes", False)):
            for order, item in enumerate(entry.get(starter) or []):
                player = item.get("player") or {}
                name = (player.get("name") or "").strip()
                if not name:
                    continue
                session.add(
                    MatchLineupPlayer(
                        lineup_id=lineup.id,
                        name=name,
                        shirt_number=_shirt_number(player.get("number")),
                        position=(player.get("pos") or None),
                        grid=player.get("grid") or existing_grid.get(name.casefold()),
                        is_starter=group,
                        display_order=order,
                    )
                )

    await session.flush()
    return result


async def sync_lineups_for_club(
    session: AsyncSession, client: ApiFootball, *, provider_team_id: str, limit: int = 2
) -> SyncResult:
    """Team sheets for what is about to kick off, or just has.

    Deliberately narrow. The provider publishes a lineup about an hour before
    kick-off, so asking about next Saturday spends a call to be told nothing.
    The window is the match that is on, and the one starting shortly.
    """
    total = SyncResult()

    club_link = await session.scalar(
        select(ProviderLink).where(
            ProviderLink.provider == PROVIDER,
            ProviderLink.entity_type == "DIRECTORY_CLUB",
            ProviderLink.provider_id == str(provider_team_id),
        )
    )
    if club_link is None:
        return total

    now = datetime.now(UTC)
    candidates = list(
        await session.scalars(
            select(Match)
            .where(
                or_(
                    Match.home_club_id == club_link.local_id,
                    Match.away_club_id == club_link.local_id,
                ),
                Match.source == PROVIDER,
                Match.status.in_(("SCHEDULED", "LIVE", "FINISHED")),
                Match.kickoff_at.isnot(None),
                # From ninety minutes before kick-off to a few hours after: the
                # window in which a sheet exists and can still change.
                Match.kickoff_at >= now - timedelta(hours=4),
                Match.kickoff_at <= now + timedelta(minutes=90),
            )
            .order_by(Match.kickoff_at)
            .limit(limit)
        )
    )

    for match in candidates:
        one = await sync_match_lineups(session, client, match=match)
        total.created += one.created
        total.updated += one.updated

    return total
