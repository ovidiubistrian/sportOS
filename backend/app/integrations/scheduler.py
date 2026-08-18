"""The league-feed scheduler.

Runs beside the outbox relay rather than inside the API, for the same reason
the relay does: this is long-lived work on a timer, and a request thread is the
wrong place for it. It ticks once a minute and asks a simple question of every
club that has connected a feed — is anything due?

Three rules keep a shared API allowance from being spent carelessly:

* **Live polling only while a match is on.** A club with `sync_live` set is
  polled between kick-off and roughly full time, and not at all the rest of the
  week. A ten-minute interval then costs about a dozen calls per match rather
  than 144 a day.
* **Fixtures on a long interval.** A calendar changes rarely; twice a day is
  plenty, and the club can always pull one by hand.
* **Standings after fixtures, never on their own timer.** A table is a
  consequence of results, so it is refreshed when results are.

Failures are recorded on the club's own row and do not stop the loop: one club
with a bad team id must not stop every other club from syncing.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import or_, select

from app.competitions.models import Match
from app.core.db import platform_session
from app.core.logging import configure_logging
from app.core.model_registry import *  # noqa: F403  registers all metadata
from app.integrations.api_football import sync as syncer
from app.integrations.api_football.client import (
    PROVIDER,
    ApiFootball,
    ProviderNotConfigured,
    ProviderUnavailable,
)
from app.integrations.models import ClubFeed, ProviderLink, SyncRun

log = structlog.get_logger("feed-scheduler")

TICK_SECONDS = 60

# How long after kick-off a match is still worth polling. Ninety minutes plus
# half-time, stoppage and the wait for the final whistle to be recorded.
# Kick-off plus the match itself plus the hour after it. A fixture that
# started three hours ago is finished whatever the provider still says.
MATCH_WINDOW = timedelta(hours=3)


async def _club_directory_id(session, provider_team_id: str):
    link = await session.scalar(
        select(ProviderLink).where(
            ProviderLink.provider == PROVIDER,
            ProviderLink.entity_type == "DIRECTORY_CLUB",
            ProviderLink.provider_id == str(provider_team_id),
        )
    )
    return link.local_id if link else None


# How often to ask, by how close the football is. Answered from our own
# calendar rather than by asking the provider, which would cost a call to find
# out whether to spend a call.
#
# The shape of it matters more than the numbers. Polling on a fixed interval
# all week spends an allowance on a calendar that changes twice a season; not
# polling until kick-off misses the team sheets, which the provider publishes
# about an hour before. So the cadence follows the match: quiet, then watchful,
# then every minute while it is actually on.
BUILD_UP = timedelta(hours=1)
BUILD_UP_INTERVAL = timedelta(minutes=15)
LIVE_INTERVAL = timedelta(minutes=1)


async def _live_cadence(session, provider_team_id: str) -> timedelta | None:
    """How often this club should be polled right now, or `None` for not at all.

    `None` is the answer on all but a handful of days a season, and that is the
    point: between matches there is nothing to learn, and a fixture list that
    moves is caught by the twice-daily fixtures sync instead.
    """
    club_id = await _club_directory_id(session, provider_team_id)
    if club_id is None:
        return None

    now = datetime.now(UTC)
    kickoff = await session.scalar(
        select(Match.kickoff_at).where(
            or_(Match.home_club_id == club_id, Match.away_club_id == club_id),
            Match.source == PROVIDER,
            Match.status.in_(("SCHEDULED", "LIVE")),
            Match.kickoff_at.isnot(None),
            # From the build-up to the end of the window a match can still be
            # in. Anything outside it is not today's business.
            Match.kickoff_at >= now - MATCH_WINDOW,
            Match.kickoff_at <= now + BUILD_UP,
        )
    )
    if kickoff is None:
        return None

    # Kicked off and not yet out of the window: the score is changing.
    if kickoff <= now:
        return LIVE_INTERVAL

    # Still to come. Watch loosely — this is the window in which the team
    # sheets appear, and nothing else changes.
    return BUILD_UP_INTERVAL


def _due(last: datetime | None, every: timedelta) -> bool:
    return last is None or datetime.now(UTC) - last >= every


async def _record(session, kind: str, feed: ClubFeed, result, error: str | None) -> None:
    started = datetime.now(UTC)
    session.add(
        SyncRun(
            provider=PROVIDER,
            kind=kind,
            tenant_id=feed.tenant_id,
            started_at=started,
            finished_at=started,
            status="FAILED" if error else "OK",
            requests=getattr(result, "requests", 0),
            created=getattr(result, "created", 0),
            updated=getattr(result, "updated", 0),
            error=error[:500] if error else None,
        )
    )


async def sync_one(feed: ClubFeed) -> None:
    """Whatever this club is due for, in one API session."""
    fixtures_due = feed.sync_fixtures and _due(
        feed.last_fixtures_at, timedelta(hours=feed.fixtures_interval_hours)
    )

    async with platform_session(
        reason=f"scheduled league-feed sync for club {feed.club_id}", routine=True
    ) as session:
        # The club's configured interval is now a floor, not the schedule: it
        # stops an over-eager setting from polling faster than the football
        # actually changes, and the cadence decides the rest.
        cadence = (
            await _live_cadence(session, feed.provider_team_id or "")
            if feed.sync_live
            else None
        )
        live_due = cadence is not None and _due(
            feed.last_live_at,
            max(cadence, timedelta(minutes=min(feed.live_interval_minutes, 1))),
        )
        if not fixtures_due and not live_due:
            return

        try:
            async with ApiFootball() as client:
                if fixtures_due:
                    result = await syncer.sync_club_fixtures(
                        session,
                        client,
                        provider_team_id=feed.provider_team_id or "",
                        season_year=feed.season_year or 0,
                    )
                    if feed.sync_standings:
                        for league in await syncer.leagues_played(
                            session, provider_team_id=feed.provider_team_id or ""
                        ):
                            await syncer.sync_league_fixtures(
                                session,
                                client,
                                provider_league=league,
                                provider_season=feed.season_year or 0,
                            )
                            await syncer.sync_standings(
                                session,
                                client,
                                provider_league=league,
                                provider_season=feed.season_year or 0,
                            )
                    # Events ride along with fixtures: a match report is only
                    # interesting once the result that produced it is in.
                    await syncer.sync_events_for_club(
                        session, client, provider_team_id=feed.provider_team_id or ""
                    )
                    await _record(session, "FIXTURES", feed, result, None)
                    log.info(
                        "fixtures_synced",
                        club_id=str(feed.club_id),
                        created=result.created,
                        updated=result.updated,
                        requests=client.usage.requests,
                        remaining=client.usage.remaining,
                    )

                if live_due:
                    live = await syncer.sync_live_for_club(
                        session, client, provider_team_id=feed.provider_team_id or ""
                    )
                    # While a match is on, the goals are the point.
                    await syncer.sync_events_for_club(
                        session, client, provider_team_id=feed.provider_team_id or "", limit=2
                    )
                    # And who is on the pitch. The provider publishes a team
                    # sheet about an hour before kick-off, so this only ever
                    # asks about a match that is on or about to be — see
                    # `sync_lineups_for_club`.
                    await syncer.sync_lineups_for_club(
                        session, client, provider_team_id=feed.provider_team_id or ""
                    )
                    await _record(session, "LIVE", feed, live, None)
                    log.info(
                        "live_synced",
                        club_id=str(feed.club_id),
                        updated=live.updated,
                        remaining=client.usage.remaining,
                    )
        except ProviderNotConfigured:
            # Nothing to say once a minute about a key nobody has set.
            return
        except ProviderUnavailable as exc:
            await _record(session, "FIXTURES" if fixtures_due else "LIVE", feed, None, str(exc))
            log.warning("feed_sync_failed", club_id=str(feed.club_id), error=str(exc))

    # Timestamps live on a tenant-scoped row, so they are written separately
    # from the platform session that wrote the shared fixtures.
    async with platform_session(
        reason=f"record league-feed sync times for club {feed.club_id}", routine=True
    ) as session:
        row = await session.get(ClubFeed, feed.id)
        if row is None:
            return
        now = datetime.now(UTC)
        if fixtures_due:
            row.last_fixtures_at = now
        if live_due:
            row.last_live_at = now


async def tick() -> None:
    async with platform_session(
        reason="find clubs due a league-feed sync", routine=True
    ) as session:
        feeds = list(
            await session.scalars(
                select(ClubFeed).where(
                    ClubFeed.provider == PROVIDER,
                    ClubFeed.mode == "FEED",
                    ClubFeed.provider_team_id.isnot(None),
                )
            )
        )

    for feed in feeds:
        try:
            await sync_one(feed)
        except Exception as exc:
            log.exception("feed_sync_crashed", club_id=str(feed.club_id), error=str(exc))


async def run() -> None:
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stopping.set)

    log.info("feed_scheduler_started", tick_seconds=TICK_SECONDS)
    while not stopping.is_set():
        try:
            await tick()
        except Exception as exc:
            log.exception("feed_tick_failed", error=str(exc))
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stopping.wait(), timeout=TICK_SECONDS)
    log.info("feed_scheduler_stopped")


def main() -> None:
    configure_logging()
    asyncio.run(run())


if __name__ == "__main__":
    main()
