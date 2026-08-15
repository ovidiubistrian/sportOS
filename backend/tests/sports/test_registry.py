"""One platform, several team sports.

Two things are being proved here, and the first matters more than the second.

**Football did not move.** The rules that used to be hardcoded now come from a
profile, and the profile has to give back exactly what was there before — three
points for a win, one for a draw, the same ten positions, the same four event
kinds. Everything else in the suite is the wider proof; this is the direct one.

**A second sport is describable without touching a screen.** Handball, with two
points for a win and a suspension instead of a substitution, and basketball,
where a drawn result cannot reach a table at all.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.sports.registry import (
    ALL_EVENT_KINDS,
    ALL_POSITIONS,
    BY_KEY,
    DEFAULT_SPORT,
    SPORTS,
    profile,
)

pytestmark = pytest.mark.sports

BASE = "/api/v1"


class TestFootballIsUnchanged:
    def test_the_points_are_the_ones_that_were_hardcoded(self) -> None:
        football = profile("FOOTBALL")
        assert (football.points_for_win, football.points_for_draw) == (3, 1)
        assert football.draws_possible

    def test_the_positions_are_the_ones_that_were_hardcoded(self) -> None:
        assert profile("FOOTBALL").positions == (
            "GK",
            "RB",
            "CB",
            "LB",
            "DM",
            "CM",
            "AM",
            "RW",
            "LW",
            "ST",
        )

    def test_the_event_kinds_are_the_ones_that_were_hardcoded(self) -> None:
        assert profile("FOOTBALL").event_kinds == ("GOAL", "CARD", "SUBSTITUTION", "VAR")

    def test_it_is_what_everything_defaults_to(self) -> None:
        """Every existing row got FOOTBALL, so nothing had to be migrated."""
        assert DEFAULT_SPORT == "FOOTBALL"
        assert profile(None).key == "FOOTBALL"
        assert profile("").key == "FOOTBALL"

    def test_an_unknown_sport_falls_back_rather_than_failing(self) -> None:
        """A sport removed under live rows must not take a club's site down."""
        assert profile("QUIDDITCH").key == "FOOTBALL"


class TestASecondSport:
    def test_handball_wins_are_worth_two(self) -> None:
        handball = profile("HANDBALL")
        assert (handball.points_for_win, handball.points_for_draw) == (2, 1)
        assert handball.draws_possible

    def test_handball_has_suspensions_rather_than_only_substitutions(self) -> None:
        assert "SUSPENSION" in profile("HANDBALL").event_kinds

    def test_basketball_cannot_be_drawn(self) -> None:
        """Overtime is played until somebody wins, so no draw reaches a table."""
        basketball = profile("BASKETBALL")
        assert basketball.draws_possible is False
        assert basketball.points_for_draw == 0

    def test_what_is_scored_is_not_always_a_goal(self) -> None:
        assert profile("BASKETBALL").scoring_unit == "POINT"
        assert profile("VOLLEYBALL").scoring_unit == "SET"
        assert profile("FOOTBALL").scoring_unit == "GOAL"

    def test_volleyball_has_no_clock(self) -> None:
        """A set is played to a score, so "73'" is not a thing to record."""
        volleyball = profile("VOLLEYBALL")
        assert volleyball.tracks_minute is False
        assert volleyball.counts_sets is True

    def test_only_football_has_a_feed(self) -> None:
        """Everything else is entered by hand — the same as Liga 4 football."""
        with_provider = [sport.key for sport in SPORTS if sport.provider]
        assert with_provider == ["FOOTBALL"]


class TestTheStorageVocabulary:
    """One column has to hold every sport's words."""

    def test_every_sports_events_are_storable(self) -> None:
        for sport in SPORTS:
            assert set(sport.event_kinds) <= set(ALL_EVENT_KINDS)

    def test_every_sports_positions_are_storable(self) -> None:
        for sport in SPORTS:
            assert set(sport.positions) <= set(ALL_POSITIONS)

    def test_no_position_is_too_long_for_the_column(self) -> None:
        """`primary_position` is varchar(12); "UNIVERSAL" already needs nine."""
        assert max(len(position) for position in ALL_POSITIONS) <= 12

    def test_every_sport_names_positions(self) -> None:
        """A squad screen with no positions to choose from is not shippable."""
        for sport in SPORTS:
            assert sport.positions, f"{sport.key} has no positions"


class TestTheApi:
    async def test_a_club_can_read_what_sports_exist(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        response = await client.get(f"{BASE}/sports", headers=as_user("owner"))
        assert response.status_code == 200

        by_key = {row["key"]: row for row in response.json()}
        assert set(by_key) == set(BY_KEY)
        assert by_key["FOOTBALL"]["has_provider"] is True
        assert by_key["HANDBALL"]["has_provider"] is False

    async def test_the_demo_club_is_still_football(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        """The migration defaulted every existing row, and nothing moved."""
        teams = (await client.get(f"{BASE}/teams", headers=as_user("owner"))).json()
        assert teams
        assert {team.get("sport", "FOOTBALL") for team in teams} == {"FOOTBALL"}
