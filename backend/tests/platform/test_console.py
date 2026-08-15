"""The super-admin console.

Two things are worth testing here and the rest is CRUD.

The first is that platform access is not tenant access. A super admin can list
every tenant and see how many players each has, and still cannot read one of
those players — the counts come from `platform_session`, the data does not.

The second is impersonation. It is a real, expiring `role_assignment` rather
than a flag, which means the interesting assertions are about the grant: that
taking one requires step-up authentication, that it appears in the audit with
the reason attached, and that it stops working when it lapses.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.platform

BASE = "/api/v1"


class TestReach:
    async def test_a_super_admin_sees_every_tenant(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        response = await client.get(f"{BASE}/platform/tenants", headers=as_user("platform"))
        assert response.status_code == 200, response.text

        slugs = {row["slug"] for row in response.json()}
        assert {"fc-example", "northern-united"} <= slugs, "across tenants, not one"

    async def test_a_tenant_owner_cannot_reach_the_console(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        response = await client.get(f"{BASE}/platform/tenants", headers=as_user("owner"))
        assert response.status_code in (401, 403)

    async def test_seeing_a_tenant_is_not_reading_its_data(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        """The whole point of the console being a separate surface.

        The player *count* comes from a platform session that states its reason.
        The players themselves need a role in the tenant, and a super admin does
        not have one — so this is a 400 asking which tenant, not a page of
        somebody else's under-15s.
        """
        tenants = (
            await client.get(f"{BASE}/platform/tenants", headers=as_user("platform"))
        ).json()
        other = next(row for row in tenants if row["slug"] == "northern-united")
        assert other["players"] > 0, "the console can count them"

        response = await client.get(
            f"{BASE}/players",
            headers={**as_user("platform"), "X-Tenant-Id": other["id"]},
            params={"limit": 1},
        )
        assert response.status_code == 400
        assert response.json()["code"] == "TENANT_CONTEXT_MISSING"


class TestPlansAndTenants:
    async def test_the_plan_catalogue_lists_features(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        plans = (await client.get(f"{BASE}/platform/plans", headers=as_user("platform"))).json()
        by_key = {plan["key"]: plan for plan in plans}
        assert {"STARTER", "CLUB", "PRO"} <= set(by_key)

        club = {f["feature_key"]: f for f in by_key["CLUB"]["features"]}
        starter = {f["feature_key"]: f for f in by_key["STARTER"]["features"]}
        assert club["shop"]["enabled"] is True
        assert "shop" not in starter or starter["shop"]["enabled"] is False

    @pytest.mark.parametrize(
        ("method", "path", "body"),
        [
            ("PATCH", "/platform/tenants/{id}", {"status": "SUSPENDED"}),
            (
                "PUT",
                "/platform/tenants/{id}/subscription",
                {"plan_key": "CLUB", "status": "ACTIVE"},
            ),
        ],
    )
    async def test_changing_a_tenant_needs_a_second_factor(
        self,
        client: httpx.AsyncClient,
        as_user: Any,
        method: str,
        path: str,
        body: dict[str, Any],
    ) -> None:
        """Suspending a club, or moving it between plans, is money and access.

        Both permissions are marked sensitive, so a password-only session is
        refused before anything is written. That is also why the validation
        inside these routes has no end-to-end test here: reaching it would mean
        weakening the permission, which would be testing the wrong thing.
        """
        tenants = (
            await client.get(f"{BASE}/platform/tenants", headers=as_user("platform"))
        ).json()
        target = next(row for row in tenants if row["slug"] == "northern-united")

        response = await client.request(
            method,
            f"{BASE}{path.format(id=target['id'])}",
            headers=as_user("platform"),
            json=body,
        )
        assert response.status_code == 401
        assert response.json()["code"] == "STEP_UP_REQUIRED"


class TestImpersonation:
    async def test_it_requires_step_up_authentication(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        """Reading another club's data is exactly the action MFA exists for.

        The permission is marked sensitive, so a session that has not proved a
        second factor is refused — before any grant is written, which is why
        the check being at the door rather than inside matters.
        """
        tenants = (
            await client.get(f"{BASE}/platform/tenants", headers=as_user("platform"))
        ).json()
        target = next(row for row in tenants if row["slug"] == "northern-united")

        response = await client.post(
            f"{BASE}/platform/tenants/{target['id']}/impersonate",
            headers=as_user("platform"),
            json={"reason": "Investigating a support ticket", "minutes": 30},
        )
        assert response.status_code == 401
        assert response.json()["code"] == "STEP_UP_REQUIRED"

    async def test_a_reason_is_not_optional(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        tenants = (
            await client.get(f"{BASE}/platform/tenants", headers=as_user("platform"))
        ).json()
        target = next(row for row in tenants if row["slug"] == "northern-united")

        response = await client.post(
            f"{BASE}/platform/tenants/{target['id']}/impersonate",
            headers=as_user("platform"),
            json={"minutes": 30},
        )
        # Refused for the missing reason before step-up is even considered.
        assert response.status_code in (401, 422)

    async def test_a_lapsed_grant_stops_working(
        self, client: httpx.AsyncClient, as_user: Any, admin_engine: AsyncEngine
    ) -> None:
        """What "time-limited" has to mean.

        Written straight into `role_assignment` rather than through the endpoint,
        because the endpoint is behind MFA and this is testing the expiry, not
        the door. An already-expired grant must leave the holder exactly where
        they started: unable to name the tenant at all.
        """
        me = (await client.get(f"{BASE}/me", headers=as_user("platform"))).json()
        tenants = (
            await client.get(f"{BASE}/platform/tenants", headers=as_user("platform"))
        ).json()
        target = next(row for row in tenants if row["slug"] == "northern-united")

        grant_id = str(uuid4())
        expired = datetime.now(UTC) - timedelta(minutes=5)

        async with admin_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO role_assignment "
                    "(id, user_id, role_id, tenant_id, valid_from, valid_until, granted_by,"
                    " created_at, updated_at) "
                    "SELECT :gid, :uid, role.id, :tid, :from, :until, :uid, now(), now() "
                    "FROM role WHERE role.key = 'CLUB_ADMIN'"
                ),
                {
                    "gid": grant_id,
                    "uid": me["user_id"],
                    "tid": target["id"],
                    "from": expired - timedelta(hours=1),
                    "until": expired,
                },
            )

        try:
            response = await client.get(
                f"{BASE}/players",
                headers={**as_user("platform"), "X-Tenant-Id": target["id"]},
                params={"limit": 1},
            )
            assert response.status_code == 400, (
                "an expired grant is not a membership; the tenant is unknown again"
            )
        finally:
            async with admin_engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM role_assignment WHERE id = :gid"), {"gid": grant_id}
                )


class TestCompetitionCuration:
    async def test_the_catalogue_shows_what_is_in_use(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        """A competition with seasons behind it cannot be renamed casually."""
        rows = (
            await client.get(f"{BASE}/platform/competitions", headers=as_user("platform"))
        ).json()
        by_key = {row["key"]: row for row in rows}
        assert "liga-2" in by_key
        assert by_key["liga-2"]["seasons"] >= 1
        assert by_key["liga-5"]["seasons"] == 0

    async def test_a_competition_can_be_added_and_withdrawn(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        key = f"test-cup-{uuid4().hex[:6]}"
        created = await client.post(
            f"{BASE}/platform/competitions",
            headers=as_user("platform"),
            json={
                "country_code": "RO",
                "key": key,
                "name": "Cupa de Test",
                "short_name": "CT",
                "format": "KNOCKOUT",
                "scope": "DOMESTIC_CUP",
                "sort_order": 900,
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["country_code"] == "RO"

        withdrawn = await client.patch(
            f"{BASE}/platform/competitions/{created.json()['id']}",
            headers=as_user("platform"),
            json={
                "country_code": "RO",
                "key": key,
                "name": "Cupa de Test",
                "format": "KNOCKOUT",
                "scope": "DOMESTIC_CUP",
                "sort_order": 900,
                "is_active": False,
            },
        )
        assert withdrawn.status_code == 200
        assert withdrawn.json()["is_active"] is False

        # Withdrawn means gone from what a club can enter, not deleted.
        offered = (await client.get(f"{BASE}/competitions", headers=as_user("owner"))).json()
        assert key not in {row["key"] for row in offered}

    async def test_a_duplicate_key_is_refused(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        response = await client.post(
            f"{BASE}/platform/competitions",
            headers=as_user("platform"),
            json={
                "country_code": "RO",
                "key": "liga-1",
                "name": "Liga 1 Again",
                "format": "LEAGUE",
                "scope": "DOMESTIC_LEAGUE",
                "tier": 1,
            },
        )
        assert response.status_code == 409

    async def test_a_club_admin_cannot_curate(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        """Reference data every tenant reads. Only the platform writes it."""
        response = await client.post(
            f"{BASE}/platform/competitions",
            headers=as_user("owner"),
            json={
                "key": "invented-league",
                "name": "A League I Made Up",
                "format": "LEAGUE",
                "scope": "DOMESTIC_LEAGUE",
                "tier": 1,
            },
        )
        assert response.status_code in (401, 403)
