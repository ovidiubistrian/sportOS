"""The league feed.

No key is needed to run these and none is used: the interesting behaviour is
what we do with the provider's answers, not that httpx can make a request. The
payloads below are the shape API-Football actually returns, trimmed to the
fields the sync reads.

What is worth asserting is the decisions — adopting a fixture a club already
entered instead of duplicating it, keeping a status and a score in agreement,
and refusing to let a club edit a row the feed now owns.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.competitions.models import CompetitionSeason, DirectoryClub, Match
from app.core.config import settings
from app.integrations.api_football import sync as syncer
from app.integrations.api_football.client import ApiFootball, Usage

pytestmark = pytest.mark.integrations

BASE = "/api/v1"


class FakeApi(ApiFootball):
    """Answers from a canned payload, counting calls like the real one."""

    def __init__(self, fixtures: list[dict[str, Any]]) -> None:
        super().__init__(usage=Usage())
        self._fixtures = fixtures

    async def fixtures(self, **_: Any) -> list[dict[str, Any]]:
        self.usage.requests += 1
        self.usage.remaining = 99
        return self._fixtures

    async def live_fixtures(self, **_: Any) -> list[dict[str, Any]]:
        self.usage.requests += 1
        return self._fixtures


def payload_for(
    *,
    provider_id: int,
    home: tuple[int, str],
    away: tuple[int, str],
    kickoff: datetime,
    status: str = "NS",
    goals: tuple[int | None, int | None] = (None, None),
    elapsed: int | None = None,
) -> dict[str, Any]:
    return {
        "fixture": {
            "id": provider_id,
            "date": kickoff.isoformat(),
            "status": {"short": status, "elapsed": elapsed},
            "venue": {"name": "Stadionul Test"},
        },
        "league": {"round": "Regular Season - 15"},
        "teams": {
            "home": {"id": home[0], "name": home[1], "logo": "https://example.test/h.png"},
            "away": {"id": away[0], "name": away[1], "logo": "https://example.test/a.png"},
        },
        "goals": {"home": goals[0], "away": goals[1]},
    }


@pytest.fixture
async def platform_db() -> AsyncIterator[AsyncSession]:
    """A platform-role session on its own engine, one per test.

    Not `platform_session`: that uses the module-level engine, whose pool is
    bound to whichever event loop imported it, while pytest-asyncio gives every
    test a fresh one. Sharing it makes a test pass alone and fail in a suite —
    the same reason `admin_engine` exists in conftest.
    """
    engine = create_async_engine(settings.database_platform_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    session = factory()
    try:
        yield session
        await session.commit()
    finally:
        await session.close()
        await engine.dispose()


@pytest.fixture
async def season(
    client: httpx.AsyncClient, as_user: Any, platform_db: AsyncSession
) -> AsyncIterator[CompetitionSeason]:
    """A throwaway competition and season, so the demo's own stay untouched."""
    created = await client.post(
        f"{BASE}/platform/competitions",
        headers=as_user("platform"),
        json={
            "country_code": "RO",
            "key": f"feed-test-{uuid4().hex[:6]}",
            "name": "Feed Test League",
            "format": "LEAGUE",
            "scope": "DOMESTIC_LEAGUE",
            "tier": 5,
            "sort_order": 990,
        },
    )
    assert created.status_code == 201, created.text

    row = CompetitionSeason(
        competition_id=UUID(created.json()["id"]),
        name="2025/26",
        start_date=datetime(2025, 7, 1).date(),
        end_date=datetime(2026, 6, 30).date(),
        is_current=True,
    )
    platform_db.add(row)
    await platform_db.flush()
    await platform_db.commit()

    try:
        yield row
    finally:
        for statement in (
            "DELETE FROM provider_link WHERE entity_type = 'MATCH' AND local_id IN "
            "(SELECT id FROM match WHERE competition_season_id = :s)",
            "DELETE FROM match WHERE competition_season_id = :s",
            "DELETE FROM competition_entry WHERE competition_season_id = :s",
            "DELETE FROM provider_link WHERE entity_type = 'COMPETITION_SEASON' "
            "AND local_id = :s",
            "DELETE FROM competition_season WHERE id = :s",
        ):
            await platform_db.execute(text(statement), {"s": str(row.id)})
        await platform_db.execute(
            text("DELETE FROM competition WHERE id = :c"),
            {"c": str(row.competition_id)},
        )
        await platform_db.commit()


async def pull(
    session: AsyncSession, season: CompetitionSeason, payload: list[dict[str, Any]]
) -> syncer.SyncResult:
    return await syncer.sync_fixtures(
        session,
        FakeApi(payload),
        season=season,
        provider_league="284",
        provider_season=2025,
    )


async def matches_in(session: AsyncSession, season: CompetitionSeason) -> list[Match]:
    return list(
        await session.scalars(select(Match).where(Match.competition_season_id == season.id))
    )


class TestPullingFixtures:
    async def test_a_scheduled_fixture_arrives_with_no_score(
        self, platform_db: AsyncSession, season: CompetitionSeason
    ) -> None:
        result = await pull(
            platform_db,
            season,
            [
                payload_for(
                    provider_id=900001,
                    home=(1001, "Feed United"),
                    away=(1002, "Feed City"),
                    kickoff=datetime.now(UTC) + timedelta(days=3),
                )
            ],
        )
        assert result.created == 1

        match = (await matches_in(platform_db, season))[0]
        assert match.source == "API_FOOTBALL"
        assert match.status == "SCHEDULED"
        assert match.home_score is None, "an unplayed fixture is not a nil-nil"
        assert match.venue_name == "Stadionul Test"

    async def test_a_live_fixture_carries_its_score(
        self, platform_db: AsyncSession, season: CompetitionSeason
    ) -> None:
        """The case that forced the check constraint to widen.

        A kicked-off match has a score from the first minute, so LIVE has to be
        allowed to store one — otherwise a live scoreboard cannot hold the
        number it exists to show.
        """
        await pull(
            platform_db,
            season,
            [
                payload_for(
                    provider_id=900002,
                    home=(1001, "Feed United"),
                    away=(1002, "Feed City"),
                    kickoff=datetime.now(UTC) - timedelta(minutes=30),
                    status="2H",
                    goals=(1, 0),
                    elapsed=63,
                )
            ],
        )
        match = (await matches_in(platform_db, season))[0]
        assert match.status == "LIVE"
        assert (match.home_score, match.away_score) == (1, 0)
        assert match.minute == 63

    async def test_a_nil_nil_kick_off_still_stores_a_score(
        self, platform_db: AsyncSession, season: CompetitionSeason
    ) -> None:
        """The provider sends null goals at kick-off; the database needs a pair."""
        await pull(
            platform_db,
            season,
            [
                payload_for(
                    provider_id=900003,
                    home=(1001, "Feed United"),
                    away=(1002, "Feed City"),
                    kickoff=datetime.now(UTC),
                    status="1H",
                    goals=(None, None),
                    elapsed=2,
                )
            ],
        )
        match = (await matches_in(platform_db, season))[0]
        assert (match.home_score, match.away_score) == (0, 0)

    async def test_syncing_twice_updates_rather_than_duplicates(
        self, platform_db: AsyncSession, season: CompetitionSeason
    ) -> None:
        args: dict[str, Any] = {
            "provider_id": 900004,
            "home": (1001, "Feed United"),
            "away": (1002, "Feed City"),
            "kickoff": datetime.now(UTC) + timedelta(days=5),
        }
        await pull(platform_db, season, [payload_for(**args)])
        again = await pull(
            platform_db, season, [payload_for(**args, status="FT", goals=(2, 1))]
        )

        assert again.created == 0 and again.updated == 1
        matches = await matches_in(platform_db, season)
        assert len(matches) == 1, "the same fixture, not a second copy"
        assert matches[0].status == "FINISHED"
        assert (matches[0].home_score, matches[0].away_score) == (2, 1)

    async def test_a_hand_entered_fixture_is_adopted_not_duplicated(
        self, platform_db: AsyncSession, season: CompetitionSeason
    ) -> None:
        """The case a club hits on the day the feed is switched on.

        They have been keeping the calendar by hand. Linking the season must
        take those fixtures over, not add a second copy of every one — which
        would count each result twice in the league table.
        """
        kickoff = datetime.now(UTC) + timedelta(days=6)
        teams: dict[str, Any] = {
            "home": (1001, "Feed United"),
            "away": (1002, "Feed City"),
        }

        # Created the way the sync resolves them, so the adoption is matched on
        # the same directory rows the provider payload will name.
        home = await syncer.ensure_club(
            platform_db, {"id": teams["home"][0], "name": teams["home"][1]}
        )
        away = await syncer.ensure_club(
            platform_db, {"id": teams["away"][0], "name": teams["away"][1]}
        )

        manual = Match(
            competition_season_id=season.id,
            home_club_id=home.id,
            away_club_id=away.id,
            round_kind="MATCHDAY",
            # A day out and the wrong time — exactly what the feed fixes.
            kickoff_at=kickoff - timedelta(days=1),
            status="SCHEDULED",
            source="CLUB",
        )
        platform_db.add(manual)
        await platform_db.flush()
        manual_id = manual.id

        result = await pull(
            platform_db,
            season,
            [payload_for(provider_id=900005, kickoff=kickoff, **teams)],
        )
        assert result.created == 0, "adopted, not created"

        matches = await matches_in(platform_db, season)
        assert len(matches) == 1
        assert matches[0].id == manual_id, "the club's own row, taken over"
        assert matches[0].source == "API_FOOTBALL"

    async def test_a_known_club_is_reused_rather_than_duplicated(
        self, platform_db: AsyncSession, season: CompetitionSeason
    ) -> None:
        """Matched by slug when the provider id is new to us.

        Without it, switching the feed on would create a second "CSM Reșița"
        and split its league table in two.
        """
        existing = await platform_db.scalar(
            select(DirectoryClub).where(DirectoryClub.slug == "csm-resita")
        )
        assert existing is not None

        club = await syncer.ensure_club(
            platform_db, {"id": 777001, "name": "CSM Reșița", "logo": None}
        )
        assert club.id == existing.id

        # The link this just wrote points a real club at an invented provider
        # id. Left behind, the next genuine sync for that club collides with it.
        await platform_db.execute(
            text("DELETE FROM provider_link WHERE provider_id = '777001'")
        )
        await platform_db.commit()


class TestAuthority:
    async def test_a_club_cannot_edit_a_fixture_the_feed_owns(
        self,
        client: httpx.AsyncClient,
        as_user: Any,
        demo: dict[str, Any],
        admin_engine: AsyncEngine,
    ) -> None:
        """One writer per row.

        An edit here would survive exactly until the next pull, so it is
        refused with a sentence rather than accepted and silently reverted.
        """
        opponent = await client.post(
            f"{BASE}/directory/clubs",
            headers=as_user("owner"),
            json={"name": f"Feed Authority {uuid4().hex[:6]}"},
        )
        assert opponent.status_code == 201, opponent.text

        entries = (
            await client.get(
                f"{BASE}/competitions/entries",
                headers=as_user("owner"),
                params={"club_id": demo["club_id"]},
            )
        ).json()
        if not entries:
            pytest.skip("the demo club is not in a competition")

        created = await client.post(
            f"{BASE}/matches",
            headers=as_user("owner"),
            json={
                "club_id": demo["club_id"],
                "competition_season_id": entries[0]["id"],
                "opponent_club_id": opponent.json()["id"],
                "at_home": True,
                "kickoff_at": (datetime.now(UTC) + timedelta(days=20)).isoformat(),
            },
        )
        assert created.status_code == 201, created.text
        match_id = created.json()["id"]
        async with admin_engine.begin() as conn:
            await conn.execute(
                text("UPDATE match SET source = 'API_FOOTBALL' WHERE id = :id"),
                {"id": match_id},
            )
        try:
            edited = await client.patch(
                f"{BASE}/matches/{match_id}",
                headers=as_user("owner"),
                params={"club_id": demo["club_id"]},
                json={"venue_name": "Somewhere Else"},
            )
            assert edited.status_code == 422
            assert "league feed" in edited.text

            removed = await client.delete(
                f"{BASE}/matches/{match_id}",
                headers=as_user("owner"),
                params={"club_id": demo["club_id"]},
            )
            assert removed.status_code == 422
        finally:
            async with admin_engine.begin() as conn:
                await conn.execute(
                    text("UPDATE match SET source = 'CLUB' WHERE id = :id"),
                    {"id": match_id},
                )
            await client.delete(
                f"{BASE}/matches/{match_id}",
                headers=as_user("owner"),
                params={"club_id": demo["club_id"]},
            )


class TestTheConsole:
    async def test_the_status_never_returns_the_key(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        response = await client.get(
            f"{BASE}/platform/api-football", headers=as_user("platform")
        )
        assert response.status_code == 200
        assert set(response.json()) == {
            "key_configured",
            "base_url",
            "linked_seasons",
            "requests_today",
            "last_run_at",
            "last_error",
        }

    async def test_a_club_admin_cannot_link_a_season(
        self, client: httpx.AsyncClient, as_user: Any, season: CompetitionSeason
    ) -> None:
        response = await client.post(
            f"{BASE}/platform/api-football/links",
            headers=as_user("owner"),
            json={
                "competition_season_id": str(season.id),
                "provider_league_id": "284",
                "provider_season": 2025,
            },
        )
        assert response.status_code in (401, 403)

    async def test_no_key_is_refused_with_a_sentence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A missing key is a configuration problem, said plainly.

        Tested against the client in this process rather than through the API:
        the server reads its own key from the environment, so a test that
        blanked one here would only be blanking its own copy — and would pass
        for the wrong reason on a machine where the feed genuinely works.
        """
        from pydantic import SecretStr

        from app.integrations.api_football.client import ProviderNotConfigured

        monkeypatch.setattr(settings, "api_football_key", SecretStr(""))
        with pytest.raises(ProviderNotConfigured):
            async with ApiFootball():
                pass

    async def test_unlinking_hands_the_fixtures_back(
        self,
        client: httpx.AsyncClient,
        as_user: Any,
        platform_db: AsyncSession,
        season: CompetitionSeason,
    ) -> None:
        """The matches stay — a season of results is not ours to delete."""
        linked = await client.post(
            f"{BASE}/platform/api-football/links",
            headers=as_user("platform"),
            json={
                "competition_season_id": str(season.id),
                "provider_league_id": f"8{uuid4().hex[:4]}",
                "provider_season": 2025,
            },
        )
        assert linked.status_code == 201, linked.text

        await pull(
            platform_db,
            season,
            [
                payload_for(
                    provider_id=900010,
                    home=(1001, "Feed United"),
                    away=(1002, "Feed City"),
                    kickoff=datetime.now(UTC) + timedelta(days=2),
                )
            ],
        )
        await platform_db.commit()

        unlinked = await client.delete(
            f"{BASE}/platform/api-football/links/{season.id}",
            headers=as_user("platform"),
        )
        assert unlinked.status_code == 204

        # The route committed its own transaction; this session must re-read.
        await platform_db.rollback()
        remaining = await matches_in(platform_db, season)
        assert remaining, "the fixture survives the unlink"
        assert remaining[0].source == "CLUB", "and the club can edit it again"
