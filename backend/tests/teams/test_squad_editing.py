"""Editing a squad, and moving a player between squads.

The club-facing half of the academy: rename a team, archive one that no longer
runs, correct a name someone mistyped at registration, and move a player up an
age group when they outgrow theirs.

The interesting assertions are about what editing must *not* destroy. A team is
archived rather than deleted because a season of results hangs off it, and a
registration is ended rather than updated because "which team was he in last
March?" has to stay answerable.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.teams

BASE = "/api/v1"


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:6]}"


@pytest.fixture
async def team(
    client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
) -> AsyncIterator[dict[str, Any]]:
    """A throwaway squad, so tests never edit the demo's own teams.

    Archived on the way out. There is no delete — a team is history — so the
    teardown does what a club would do, and the demo's team list stays the
    handful of squads it is meant to be rather than one per test run.
    """
    response = await client.post(
        f"{BASE}/teams",
        headers=as_user("owner"),
        json={
            "club_id": demo["club_id"],
            "name": unique("Test Squad"),
            "code": unique("TS")[:16],
            "age_group": "U13",
            "level": "YOUTH",
            "is_academy": True,
        },
    )
    assert response.status_code == 201, response.text
    created = response.json()
    try:
        yield created
    finally:
        await client.patch(
            f"{BASE}/teams/{created['id']}",
            headers=as_user("owner"),
            json={"status": "ARCHIVED"},
        )


class TestEditingATeam:
    async def test_a_team_can_be_renamed(
        self, client: httpx.AsyncClient, as_user: Any, team: dict[str, Any]
    ) -> None:
        response = await client.patch(
            f"{BASE}/teams/{team['id']}",
            headers=as_user("owner"),
            json={"name": "  Under 14 Blues  ", "age_group": "U14"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["name"] == "Under 14 Blues", "surrounding whitespace is trimmed"
        assert body["age_group"] == "U14"
        assert body["code"] == team["code"], "an absent key means unchanged"

    async def test_a_code_already_in_use_is_refused(
        self,
        client: httpx.AsyncClient,
        as_user: Any,
        demo: dict[str, Any],
        team: dict[str, Any],
    ) -> None:
        response = await client.patch(
            f"{BASE}/teams/{team['id']}",
            headers=as_user("owner"),
            json={"code": demo["teams"]["U15"]["code"]},
        )
        assert response.status_code == 409

    async def test_a_team_keeps_its_own_code(
        self, client: httpx.AsyncClient, as_user: Any, team: dict[str, Any]
    ) -> None:
        """Saving a form without touching the code must not collide with itself."""
        response = await client.patch(
            f"{BASE}/teams/{team['id']}",
            headers=as_user("owner"),
            json={"code": team["code"], "name": "Same Code, New Name"},
        )
        assert response.status_code == 200, response.text

    async def test_archiving_removes_a_team_from_the_list_without_deleting_it(
        self,
        client: httpx.AsyncClient,
        as_user: Any,
        demo: dict[str, Any],
        team: dict[str, Any],
    ) -> None:
        archived = await client.patch(
            f"{BASE}/teams/{team['id']}", headers=as_user("owner"), json={"status": "ARCHIVED"}
        )
        assert archived.status_code == 200
        assert archived.json()["status"] == "ARCHIVED"

        listed = (
            await client.get(
                f"{BASE}/teams", headers=as_user("owner"), params={"club_id": demo["club_id"]}
            )
        ).json()
        assert team["id"] not in {row["id"] for row in listed}

        # Still there, which is the whole point of archiving over deleting.
        back = await client.patch(
            f"{BASE}/teams/{team['id']}", headers=as_user("owner"), json={"status": "ACTIVE"}
        )
        assert back.status_code == 200

    async def test_an_unknown_level_is_refused(
        self, client: httpx.AsyncClient, as_user: Any, team: dict[str, Any]
    ) -> None:
        response = await client.patch(
            f"{BASE}/teams/{team['id']}", headers=as_user("owner"), json={"level": "OVERSEAS"}
        )
        assert response.status_code == 422

    async def test_a_coach_cannot_edit_a_team(
        self, client: httpx.AsyncClient, as_user: Any, team: dict[str, Any]
    ) -> None:
        response = await client.patch(
            f"{BASE}/teams/{team['id']}",
            headers=as_user("coach"),
            json={"name": "Coach's Team"},
        )
        assert response.status_code in (403, 404)

    async def test_another_tenant_cannot_edit_our_team(
        self, client: httpx.AsyncClient, as_user: Any, team: dict[str, Any]
    ) -> None:
        response = await client.patch(
            f"{BASE}/teams/{team['id']}",
            headers=as_user("other_owner"),
            json={"name": "Taken Over"},
        )
        assert response.status_code == 404


class TestCorrectingAPlayer:
    async def test_a_mistyped_name_can_be_fixed(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        """The name lives on `person`, but the club edits a player.

        And `display_name` has to follow: it is what every list and team sheet
        renders, so a corrected surname that leaves it stale is not corrected.
        """
        player_id = demo["u19_player"]["id"]
        original = (
            await client.get(f"{BASE}/players/{player_id}", headers=as_user("owner"))
        ).json()

        corrected = await client.patch(
            f"{BASE}/players/{player_id}",
            headers=as_user("owner"),
            json={"last_name": "  Corrected  "},
        )
        assert corrected.status_code == 200, corrected.text
        body = corrected.json()
        assert body["last_name"] == "Corrected"
        assert body["display_name"] == f"{body['first_name']} Corrected"
        assert body["first_name"] == original["first_name"], "only what was sent changed"

        restore = await client.patch(
            f"{BASE}/players/{player_id}",
            headers=as_user("owner"),
            json={"last_name": original["last_name"]},
        )
        assert restore.status_code == 200

    async def test_an_empty_name_is_refused(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        response = await client.patch(
            f"{BASE}/players/{demo['u19_player']['id']}",
            headers=as_user("owner"),
            json={"first_name": ""},
        )
        assert response.status_code == 422


class TestMovingAPlayer:
    async def test_a_move_ends_the_old_registration_rather_than_editing_it(
        self,
        client: httpx.AsyncClient,
        as_user: Any,
        demo: dict[str, Any],
        admin_engine: AsyncEngine,
    ) -> None:
        """A player outgrows an age group. Last season's team sheet was real.

        Read straight from the table rather than through the API: the API only
        ever shows the live registration, so it cannot tell the difference
        between a row that was ended and a row that was overwritten — which is
        exactly the difference under test.
        """
        player_id = demo["u15_player"]["id"]
        before = (
            await client.get(f"{BASE}/players/{player_id}", headers=as_user("owner"))
        ).json()
        assert before["team"]["id"] == demo["u15_team_id"]

        moved = await client.put(
            f"{BASE}/players/{player_id}/registration",
            headers=as_user("owner"),
            json={"team_id": demo["u19_team_id"], "shirt_number": 77},
        )
        assert moved.status_code == 200, moved.text
        assert moved.json()["team"]["id"] == demo["u19_team_id"]
        assert moved.json()["shirt_number"] == 77

        async with admin_engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT team_id::text, ended_on IS NULL AS live "
                        "FROM player_registration WHERE player_id = :id "
                        "ORDER BY registered_on"
                    ),
                    {"id": player_id},
                )
            ).all()

        live = [team for team, is_live in rows if is_live]
        history = [team for team, is_live in rows if not is_live]
        assert live == [demo["u19_team_id"]], "exactly one live registration, the new one"
        assert demo["u15_team_id"] in history, "the U15 spell is still on record"

        back = await client.put(
            f"{BASE}/players/{player_id}/registration",
            headers=as_user("owner"),
            json={
                "team_id": demo["u15_team_id"],
                "shirt_number": before.get("shirt_number"),
            },
        )
        assert back.status_code == 200, back.text
        assert back.json()["team"]["id"] == demo["u15_team_id"]

    async def test_a_number_already_worn_in_that_team_is_refused(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        squad = (
            await client.get(
                f"{BASE}/players",
                headers=as_user("owner"),
                params={"team_id": demo["u19_team_id"], "limit": 50},
            )
        ).json()["data"]
        taken = next(
            (
                row
                for row in squad
                if row["shirt_number"] and row["id"] != demo["u15_player"]["id"]
            ),
            None,
        )
        if taken is None:
            pytest.skip("no numbered player in the U19 squad to collide with")

        response = await client.put(
            f"{BASE}/players/{demo['u15_player']['id']}/registration",
            headers=as_user("owner"),
            json={"team_id": demo["u19_team_id"], "shirt_number": taken["shirt_number"]},
        )
        assert response.status_code == 409

    async def test_a_player_can_be_taken_out_of_a_squad(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        player_id = demo["u19_player"]["id"]
        before = (
            await client.get(f"{BASE}/players/{player_id}", headers=as_user("owner"))
        ).json()

        out = await client.put(
            f"{BASE}/players/{player_id}/registration",
            headers=as_user("owner"),
            json={"team_id": None},
        )
        assert out.status_code == 200, out.text
        assert out.json()["team"] is None

        back = await client.put(
            f"{BASE}/players/{player_id}/registration",
            headers=as_user("owner"),
            json={
                "team_id": before["team"]["id"],
                "shirt_number": before.get("shirt_number"),
            },
        )
        assert back.status_code == 200, back.text

    async def test_another_tenant_cannot_move_our_player(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        response = await client.put(
            f"{BASE}/players/{demo['u19_player']['id']}/registration",
            headers=as_user("other_owner"),
            json={"team_id": None},
        )
        assert response.status_code == 404
