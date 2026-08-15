"""Fixtures, results and the table they produce.

Competitions are the one part of the product where tenants share data. Two
clubs in the same division read the same season, the same opponents and the
same table — which means the interesting tests here are not "can a club add a
fixture" but "can a club change a fixture that is not its own", and "does the
table still add up when it tries".

Written as a sequence rather than a matrix: a fixture needs a competition, a
result needs a fixture, and a table needs results. Asserting on them
independently would mean mocking the very thing under test.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest

pytestmark = pytest.mark.competitions

BASE = "/api/v1"


def unique(prefix: str) -> str:
    return f"{prefix} {uuid4().hex[:8]}"


@pytest.fixture(scope="session")
def season_name() -> str:
    """A season of this run's own.

    Competitions are shared platform data: every tenant reads the same Liga 2.
    A test that entered the real 2025/26 season would leave its throwaway
    opponents in the table the demo club shows on its website.
    """
    return f"T{uuid4().hex[:10]}"


@pytest.fixture
async def season(
    client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any], season_name: str
) -> str:
    """A season of Liga 2 the demo club is entered in."""
    competitions = (await client.get(f"{BASE}/competitions", headers=as_user("owner"))).json()
    liga2 = next(c for c in competitions if c["key"] == "liga-2")

    await client.post(
        f"{BASE}/competitions/join",
        headers=as_user("owner"),
        json={
            "club_id": demo["club_id"],
            "competition_id": liga2["id"],
            "season_name": season_name,
            "start_date": "2025-07-01",
            "end_date": "2026-06-30",
        },
    )

    entries = (
        await client.get(
            f"{BASE}/competitions/entries",
            headers=as_user("owner"),
            params={"club_id": demo["club_id"]},
        )
    ).json()
    entry = next(row for row in entries if row["season_name"] == season_name)
    return str(entry["id"])


async def make_opponent(client: httpx.AsyncClient, as_user: Any, name: str) -> dict[str, Any]:
    response = await client.post(
        f"{BASE}/directory/clubs", headers=as_user("owner"), json={"name": name}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def make_fixture(
    client: httpx.AsyncClient,
    as_user: Any,
    demo: dict[str, Any],
    season: str,
    opponent: dict[str, Any],
    *,
    at_home: bool = True,
    days: int = 7,
) -> dict[str, Any]:
    """A fixture on the demo club, removed again by the `swept` fixture.

    Left behind, they accumulate across runs until the demo club's own fixture
    list is mostly test data — and a `GET /matches` limit that used to hold the
    whole season starts truncating real matches.
    """

    response = await client.post(
        f"{BASE}/matches",
        headers=as_user("owner"),
        json={
            "club_id": demo["club_id"],
            "competition_season_id": season,
            "opponent_club_id": opponent["id"],
            "at_home": at_home,
            "round_kind": "MATCHDAY",
            "round_number": 1,
            "kickoff_at": (datetime.now(UTC) + timedelta(days=days)).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    created = response.json()
    CREATED_MATCHES.append(created["id"])
    return created


CREATED_MATCHES: list[str] = []


@pytest.fixture(autouse=True)
async def swept(
    client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
) -> AsyncIterator[None]:
    """Remove every fixture a test created, played ones included."""
    CREATED_MATCHES.clear()
    yield
    for match_id in CREATED_MATCHES:
        # A played match cannot be deleted, so unplay it first — the endpoint is
        # protecting real results, and these are not.
        await client.patch(
            f"{BASE}/matches/{match_id}",
            headers=as_user("owner"),
            params={"club_id": demo["club_id"]},
            json={"status": "SCHEDULED", "home_score": None, "away_score": None},
        )
        await client.delete(
            f"{BASE}/matches/{match_id}",
            headers=as_user("owner"),
            params={"club_id": demo["club_id"]},
        )
    CREATED_MATCHES.clear()


class TestEnteringACompetition:
    async def test_a_club_sees_the_season_it_entered(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any], season: str
    ) -> None:
        entries = (
            await client.get(
                f"{BASE}/competitions/entries",
                headers=as_user("owner"),
                params={"club_id": demo["club_id"]},
            )
        ).json()
        assert any(row["id"] == season for row in entries)

    async def test_entering_the_same_season_twice_is_refused(
        self,
        client: httpx.AsyncClient,
        as_user: Any,
        demo: dict[str, Any],
        season: str,
        season_name: str,
    ) -> None:
        """Not an error the club made — but two entries would double its row."""
        competitions = (
            await client.get(f"{BASE}/competitions", headers=as_user("owner"))
        ).json()
        liga2 = next(c for c in competitions if c["key"] == "liga-2")

        response = await client.post(
            f"{BASE}/competitions/join",
            headers=as_user("owner"),
            json={
                "club_id": demo["club_id"],
                "competition_id": liga2["id"],
                "season_name": season_name,
                "start_date": "2025-07-01",
                "end_date": "2026-06-30",
            },
        )
        assert response.status_code == 409

    async def test_a_season_must_end_after_it_starts(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        competitions = (
            await client.get(f"{BASE}/competitions", headers=as_user("owner"))
        ).json()
        cup = next(c for c in competitions if c["key"] == "cupa-romaniei")

        response = await client.post(
            f"{BASE}/competitions/join",
            headers=as_user("owner"),
            json={
                "club_id": demo["club_id"],
                "competition_id": cup["id"],
                "season_name": "backwards",
                "start_date": "2026-06-30",
                "end_date": "2025-07-01",
            },
        )
        assert response.status_code == 422


class TestTheOpponentDirectory:
    async def test_the_same_name_resolves_to_the_same_club(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        """Two clubs in a division will both add their shared opponent.

        The second is not making a mistake, and if it got its own row the two
        would file results against different clubs and the table would show the
        opponent twice.
        """
        name = unique("Directory Twin")
        first = await make_opponent(client, as_user, name)
        second = await make_opponent(client, as_user, name.upper())
        assert first["id"] == second["id"]

    async def test_a_name_with_no_letters_is_refused(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        response = await client.post(
            f"{BASE}/directory/clubs", headers=as_user("owner"), json={"name": "--- ---"}
        )
        assert response.status_code == 422

    async def test_search_narrows_to_a_season(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any], season: str
    ) -> None:
        """A fixture form wants this division, not the whole platform."""
        stranger = await make_opponent(client, as_user, unique("Unentered Club"))

        in_season = (
            await client.get(
                f"{BASE}/directory/clubs",
                headers=as_user("owner"),
                params={"season_id": season, "limit": 100},
            )
        ).json()
        assert stranger["id"] not in {club["id"] for club in in_season}


class TestFixturesAndResults:
    async def test_a_fixture_appears_in_the_club_list(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any], season: str
    ) -> None:
        opponent = await make_opponent(client, as_user, unique("Fixture Opponent"))
        match = await make_fixture(client, as_user, demo, season, opponent)

        assert match["is_home"] is True
        assert match["away"]["id"] == opponent["id"]

        upcoming = (
            await client.get(
                f"{BASE}/matches",
                headers=as_user("owner"),
                params={"club_id": demo["club_id"], "upcoming": True},
            )
        ).json()
        assert match["id"] in {row["id"] for row in upcoming}

    async def test_a_club_cannot_play_itself(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any], season: str
    ) -> None:
        me = (await client.get(f"{BASE}/me", headers=as_user("owner"))).json()
        own_directory_id = me["clubs"][0]["directory_club_id"]
        assert own_directory_id, "the club gets a directory row when it enters a competition"

        response = await client.post(
            f"{BASE}/matches",
            headers=as_user("owner"),
            json={
                "club_id": demo["club_id"],
                "competition_season_id": season,
                "opponent_club_id": own_directory_id,
                "at_home": True,
            },
        )
        assert response.status_code == 422

    async def test_a_score_and_a_status_have_to_agree(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any], season: str
    ) -> None:
        """The database enforces this; the API has to say so in a sentence."""
        opponent = await make_opponent(client, as_user, unique("Disagreeing Opponent"))
        match = await make_fixture(client, as_user, demo, season, opponent)

        scored_but_unplayed = await client.patch(
            f"{BASE}/matches/{match['id']}",
            headers=as_user("owner"),
            params={"club_id": demo["club_id"]},
            json={"home_score": 2, "away_score": 1},
        )
        assert scored_but_unplayed.status_code == 422

        played_but_unscored = await client.patch(
            f"{BASE}/matches/{match['id']}",
            headers=as_user("owner"),
            params={"club_id": demo["club_id"]},
            json={"status": "FINISHED"},
        )
        assert played_but_unscored.status_code == 422

    async def test_a_fixture_can_be_rescheduled(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any], season: str
    ) -> None:
        opponent = await make_opponent(client, as_user, unique("Rescheduled Opponent"))
        match = await make_fixture(client, as_user, demo, season, opponent)

        moved = (
            await client.patch(
                f"{BASE}/matches/{match['id']}",
                headers=as_user("owner"),
                params={"club_id": demo["club_id"]},
                json={"status": "POSTPONED", "kickoff_is_confirmed": False},
            )
        ).json()
        assert moved["status"] == "POSTPONED"
        assert moved["kickoff_is_confirmed"] is False


class TestSharedDataStaysHonest:
    async def test_another_tenant_cannot_rewrite_our_result(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any], season: str
    ) -> None:
        """The one guarantee that makes shared competitions safe.

        Matches are not tenant-scoped rows — RLS cannot help here — so the route
        checks that the club is actually playing in the match. A 404 rather than
        a 403: whether the fixture exists is not the other tenant's business.
        """
        opponent = await make_opponent(client, as_user, unique("Contested Opponent"))
        match = await make_fixture(client, as_user, demo, season, opponent)

        other_me = (await client.get(f"{BASE}/me", headers=as_user("other_owner"))).json()
        other_club = other_me["clubs"][0]["id"]

        response = await client.patch(
            f"{BASE}/matches/{match['id']}",
            headers=as_user("other_owner"),
            params={"club_id": other_club},
            json={"status": "FINISHED", "home_score": 0, "away_score": 9},
        )
        assert response.status_code == 404

        unchanged = (
            await client.get(
                f"{BASE}/matches",
                headers=as_user("owner"),
                params={"club_id": demo["club_id"]},
            )
        ).json()
        ours = next(row for row in unchanged if row["id"] == match["id"])
        assert ours["status"] == "SCHEDULED"
        assert ours["home_score"] is None

    async def test_a_club_does_not_see_another_clubs_fixtures(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any], season: str
    ) -> None:
        opponent = await make_opponent(client, as_user, unique("Private Opponent"))
        match = await make_fixture(client, as_user, demo, season, opponent)

        other_me = (await client.get(f"{BASE}/me", headers=as_user("other_owner"))).json()
        theirs = (
            await client.get(
                f"{BASE}/matches",
                headers=as_user("other_owner"),
                params={"club_id": other_me["clubs"][0]["id"]},
            )
        ).json()
        assert match["id"] not in {row["id"] for row in theirs}


class TestTheTable:
    async def test_results_add_up(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any], season: str
    ) -> None:
        """A win, a draw and a defeat: four points, and the form to match."""
        beaten = await make_opponent(client, as_user, unique("Table Beaten"))
        held = await make_opponent(client, as_user, unique("Table Held"))
        winner = await make_opponent(client, as_user, unique("Table Winner"))

        for index, (opponent, home_score, away_score) in enumerate(
            ((beaten, 3, 0), (held, 1, 1), (winner, 0, 2))
        ):
            match = await make_fixture(
                client, as_user, demo, season, opponent, days=-30 + index
            )
            recorded = await client.patch(
                f"{BASE}/matches/{match['id']}",
                headers=as_user("owner"),
                params={"club_id": demo["club_id"]},
                json={
                    "status": "FINISHED",
                    "home_score": home_score,
                    "away_score": away_score,
                },
            )
            assert recorded.status_code == 200, recorded.text

        table = (
            await client.get(f"{BASE}/competitions/{season}/table", headers=as_user("owner"))
        ).json()

        me = (await client.get(f"{BASE}/me", headers=as_user("owner"))).json()
        us = next(
            row for row in table if row["club"]["id"] == me["clubs"][0]["directory_club_id"]
        )

        assert us["played"] >= 3
        assert us["won"] >= 1 and us["drawn"] >= 1 and us["lost"] >= 1
        # Three points for the win, one for the draw — whatever else is in this
        # shared season, those three results contribute exactly four.
        assert us["points"] >= 4
        assert us["goals_for"] - us["goals_against"] == us["goal_difference"]
        # Newest first, capped at five.
        assert len(us["form"]) <= 5
        assert us["form"][0] == "L"

    async def test_the_table_is_ordered_by_points_then_goal_difference(
        self, client: httpx.AsyncClient, as_user: Any, season: str
    ) -> None:
        table = (
            await client.get(f"{BASE}/competitions/{season}/table", headers=as_user("owner"))
        ).json()

        keys = [(-row["points"], -row["goal_difference"], -row["goals_for"]) for row in table]
        assert keys == sorted(keys)
        assert [row["position"] for row in table] == list(range(1, len(table) + 1))

    async def test_an_unplayed_fixture_is_not_a_nil_nil(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any], season: str
    ) -> None:
        opponent = await make_opponent(client, as_user, unique("Unplayed Opponent"))

        before = (
            await client.get(f"{BASE}/competitions/{season}/table", headers=as_user("owner"))
        ).json()
        played_before = sum(row["played"] for row in before)

        await make_fixture(client, as_user, demo, season, opponent)

        after = (
            await client.get(f"{BASE}/competitions/{season}/table", headers=as_user("owner"))
        ).json()
        assert sum(row["played"] for row in after) == played_before
