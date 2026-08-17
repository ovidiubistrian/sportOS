"""Who may do what with a stadium, and what a tenant cannot see of another's.

Two layers, because the ticketing roles are enforced in two different places.

The role *shapes* are asserted against the templates directly. A gate operator
holding one more permission than scanning is a policy mistake, and it is worth
catching in a unit test rather than after somebody notices a steward browsing
the customer list on a borrowed handset.

Tenant isolation is asserted over HTTP with a real signed-in user from another
tenant, because that is the boundary that actually matters and the one a unit
test cannot prove: RLS, the composite foreign keys and the scope check all have
to hold together on a live request.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.authz.role_templates import BY_KEY_TEMPLATE

pytestmark = pytest.mark.permissions


class TestRoleShapes:
    """What each ticketing role is allowed to be."""

    def test_a_gate_operator_can_only_scan(self) -> None:
        """A steward's handset is lost, borrowed and left on walls.

        Whatever it can reach is what somebody who picks it up can reach, so
        the role is deliberately two permissions and no more.
        """
        held = set(BY_KEY_TEMPLATE["GATE_OPERATOR"].permissions)

        assert held == {"ticketing.access.scan", "ticketing.event.read"}
        assert not any(p.startswith("players.") for p in held)
        assert not any(p.startswith("people.") for p in held)
        assert "ticketing.order.read" not in held

    def test_the_box_office_sells_but_cannot_reprice(self) -> None:
        """Selling a ticket and deciding what it costs are different jobs."""
        held = set(BY_KEY_TEMPLATE["BOX_OFFICE"].permissions)

        assert "ticketing.order.manage" in held
        assert "ticketing.pricing.manage" not in held
        assert "ticketing.venue.manage" not in held
        assert "ticketing.allocation.manage" not in held

    def test_the_analyst_holds_nothing_that_writes(self) -> None:
        held = set(BY_KEY_TEMPLATE["TICKETING_ANALYST"].permissions)

        writes = {p for p in held if p.endswith((".manage", ".publish", ".scan"))}
        assert not writes, f"a read-only analyst may not hold {sorted(writes)}"
        assert "ticketing.report.read" in held

    def test_the_ticketing_manager_runs_the_whole_operation(self) -> None:
        held = set(BY_KEY_TEMPLATE["TICKETING_MANAGER"].permissions)

        for needed in (
            "ticketing.venue.manage",
            "ticketing.venue.publish",
            "ticketing.event.manage",
            "ticketing.pricing.manage",
            "ticketing.allocation.manage",
            "ticketing.season.manage",
        ):
            assert needed in held
        # But not the club's other business.
        assert "players.player.update" not in held
        assert not any(p.startswith("medical.") for p in held)

    def test_no_ticketing_role_reaches_clinical_data(self) -> None:
        for key in (
            "TICKETING_MANAGER",
            "BOX_OFFICE",
            "GATE_OPERATOR",
            "TICKETING_ANALYST",
        ):
            held = BY_KEY_TEMPLATE[key].permissions
            assert not any(p.startswith("medical.") for p in held), key


class TestTenantIsolation:
    """Acceptance scenario 17, over HTTP."""

    async def test_another_tenants_owner_sees_none_of_this_clubs_stadiums(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        """The strongest role in a *different* tenant is still a stranger here.

        Asserted on the list rather than on a single row: a leak that returned
        an empty list for one id and the whole table for none would pass the
        narrower test.
        """
        mine = await client.get("/api/v1/ticketing/venues", headers=as_user("owner"))
        theirs = await client.get("/api/v1/ticketing/venues", headers=as_user("other_owner"))

        assert mine.status_code == 200
        assert theirs.status_code == 200

        my_ids = {row["id"] for row in mine.json()}
        their_ids = {row["id"] for row in theirs.json()}
        assert not (my_ids & their_ids), "a stadium was visible across tenants"

    async def test_another_tenants_owner_cannot_read_this_clubs_matches(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        mine = await client.get("/api/v1/ticketing/events", headers=as_user("owner"))
        theirs = await client.get("/api/v1/ticketing/events", headers=as_user("other_owner"))

        assert mine.status_code == 200
        assert theirs.status_code == 200
        assert not ({row["id"] for row in mine.json()} & {row["id"] for row in theirs.json()})

    async def test_a_coach_cannot_reach_the_stadium_at_all(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        """Coaching a team says nothing about selling seats in the ground."""
        response = await client.get("/api/v1/ticketing/venues", headers=as_user("coach"))
        assert response.status_code == 403
        assert response.json()["code"] == "PERMISSION_DENIED"
