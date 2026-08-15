"""Scope containment.

Pure unit tests — no database, no HTTP. Containment is the rule every
authorization decision reduces to, so it gets tested directly rather than only
through the routes that use it.
"""

from __future__ import annotations

import pytest

from app.authz.permissions import EffectivePermissions
from app.authz.scope import Scope, ScopeLevel
from app.core.ids import new_id

pytestmark = pytest.mark.permissions

TENANT_A, TENANT_B = new_id(), new_id()
CLUB_A1, CLUB_A2 = new_id(), new_id()
TEAM_U15, TEAM_U17 = new_id(), new_id()


class TestContainment:
    def test_platform_contains_everything(self) -> None:
        assert Scope.platform().contains(Scope.tenant(TENANT_A))
        assert Scope.platform().contains(Scope.club(TENANT_B, CLUB_A1))
        assert Scope.platform().contains(Scope.team(TENANT_B, CLUB_A1, TEAM_U15))

    def test_nothing_below_platform_contains_platform(self) -> None:
        assert not Scope.tenant(TENANT_A).contains(Scope.platform())
        assert not Scope.club(TENANT_A, CLUB_A1).contains(Scope.platform())

    def test_tenant_grant_covers_its_clubs_and_teams(self) -> None:
        grant = Scope.tenant(TENANT_A)
        assert grant.contains(Scope.club(TENANT_A, CLUB_A1))
        assert grant.contains(Scope.team(TENANT_A, CLUB_A1, TEAM_U15))

    def test_tenant_grant_stops_at_the_tenant_boundary(self) -> None:
        assert not Scope.tenant(TENANT_A).contains(Scope.tenant(TENANT_B))
        assert not Scope.tenant(TENANT_A).contains(Scope.club(TENANT_B, CLUB_A1))

    def test_club_grant_covers_teams_in_that_club_only(self) -> None:
        grant = Scope.club(TENANT_A, CLUB_A1)
        assert grant.contains(Scope.team(TENANT_A, CLUB_A1, TEAM_U15))
        assert not grant.contains(Scope.club(TENANT_A, CLUB_A2))
        assert not grant.contains(Scope.team(TENANT_A, CLUB_A2, TEAM_U17))

    def test_team_grant_does_not_reach_a_sibling_team(self) -> None:
        grant = Scope.team(TENANT_A, CLUB_A1, TEAM_U15)
        assert grant.contains(Scope.team(TENANT_A, CLUB_A1, TEAM_U15))
        assert not grant.contains(Scope.team(TENANT_A, CLUB_A1, TEAM_U17))

    def test_team_grant_satisfies_a_broader_request_in_the_same_club(self) -> None:
        """Deliberate: a coach must be able to open the club they work in.

        Escalation is prevented elsewhere — a team role cannot hold a
        club-level *write* permission, and collection queries are narrowed by
        ScopeFilter. See Scope.contains().
        """
        grant = Scope.team(TENANT_A, CLUB_A1, TEAM_U15)
        assert grant.contains(Scope.club(TENANT_A, CLUB_A1))
        assert not grant.contains(Scope.club(TENANT_A, CLUB_A2))

    def test_team_scope_may_omit_the_club(self) -> None:
        """`?team_id=…` identifies a team without naming its club."""
        request = Scope.team(TENANT_A, None, TEAM_U15)
        assert Scope.club(TENANT_A, CLUB_A1).contains(request)
        assert not Scope.team(TENANT_A, CLUB_A1, TEAM_U17).contains(request)


class TestScopeConstruction:
    def test_narrowest_follows_the_most_specific_id(self) -> None:
        assert Scope.narrowest(TENANT_A).level is ScopeLevel.TENANT
        assert Scope.narrowest(TENANT_A, club_id=CLUB_A1).level is ScopeLevel.CLUB
        assert Scope.narrowest(TENANT_A, team_id=TEAM_U15).level is ScopeLevel.TEAM
        assert (
            Scope.narrowest(TENANT_A, club_id=CLUB_A1, team_id=TEAM_U15).level
            is ScopeLevel.TEAM
        )

    def test_incoherent_scopes_are_unrepresentable(self) -> None:
        with pytest.raises(ValueError, match="tenant_id"):
            Scope(ScopeLevel.TENANT)
        with pytest.raises(ValueError, match="club_id"):
            Scope(ScopeLevel.CLUB, tenant_id=TENANT_A)
        with pytest.raises(ValueError, match="team_id"):
            Scope(ScopeLevel.TEAM, tenant_id=TENANT_A, club_id=CLUB_A1)


class TestEffectivePermissions:
    def test_absent_permission_is_denied(self) -> None:
        effective = EffectivePermissions(grants={})
        assert not effective.allows("players.player.read", Scope.tenant(TENANT_A))

    def test_grant_applies_only_within_its_scope(self) -> None:
        effective = EffectivePermissions(
            grants={"players.player.read": frozenset({Scope.team(TENANT_A, CLUB_A1, TEAM_U15)})}
        )
        assert effective.allows("players.player.read", Scope.team(TENANT_A, CLUB_A1, TEAM_U15))
        assert not effective.allows(
            "players.player.read", Scope.team(TENANT_A, CLUB_A1, TEAM_U17)
        )
        assert not effective.allows(
            "players.player.update", Scope.team(TENANT_A, CLUB_A1, TEAM_U15)
        )

    def test_multiple_grants_are_unioned(self) -> None:
        effective = EffectivePermissions(
            grants={
                "players.player.read": frozenset(
                    {
                        Scope.team(TENANT_A, CLUB_A1, TEAM_U15),
                        Scope.team(TENANT_A, CLUB_A1, TEAM_U17),
                    }
                )
            }
        )
        for team in (TEAM_U15, TEAM_U17):
            assert effective.allows("players.player.read", Scope.team(TENANT_A, CLUB_A1, team))
