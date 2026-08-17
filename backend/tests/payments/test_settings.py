"""Setting up a club's card gateway.

The credentials a bank issues are the most dangerous thing a club keeps here:
whoever holds them can point a supporter's money somewhere else. So these tests
are about who may touch them — and about the fact that touching them at all
takes a second factor, which is the company `medical.record.write` and
`platform.impersonate` keep.

Nothing here reaches BT. A suite that dials a bank is a suite that fails when
the bank is slow.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.commerce

BASE = "/api/v1/payments"

GATEWAY = {"user_name": "club_merchant", "password": "the-bank-issued-this"}


class TestWhoMaySetItUp:
    async def test_the_academy_director_may_not(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        """Running an academy is not running the club's bank account."""
        response = await client.put(
            f"{BASE}/settings/btipay", headers=as_user("academy"), json=GATEWAY
        )
        assert response.status_code == 403

    async def test_a_coach_may_not_even_look(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        assert (
            await client.get(f"{BASE}/settings", headers=as_user("coach"))
        ).status_code == 403

    async def test_the_owner_is_asked_for_a_second_factor(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        """Holding the permission is not enough, and that is the point.

        A stolen session is the threat these credentials are worth protecting
        from, and it is the one a permission check does not address. The 401
        is not a lost session — `ApiError.needsStepUp` is what tells the two
        apart on the client.
        """
        response = await client.put(
            f"{BASE}/settings/btipay", headers=as_user("owner"), json=GATEWAY
        )
        assert response.status_code == 401
        assert response.json()["code"] == "STEP_UP_REQUIRED"

    async def test_checking_the_credentials_is_guarded_the_same_way(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        """Otherwise it is an oracle: a way to test stolen credentials against
        a bank without ever holding them."""
        response = await client.post(
            f"{BASE}/settings/btipay/test", headers=as_user("owner")
        )
        assert response.status_code == 401
        assert response.json()["code"] == "STEP_UP_REQUIRED"

        assert (
            await client.post(f"{BASE}/settings/btipay/test", headers=as_user("coach"))
        ).status_code == 403


class TestReading:
    async def test_the_owner_may_see_what_is_configured(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        """Reading is not sensitive: no secret comes back, and a club needs to
        know whether it is set up without proving itself twice."""
        response = await client.get(f"{BASE}/settings", headers=as_user("owner"))
        assert response.status_code == 200
        for row in response.json():
            assert "password" not in row, "a stored credential must not be readable"

    async def test_the_log_is_the_tenants_own(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        """It carries buyers' details and what was said to a bank about them."""
        assert (
            await client.get(f"{BASE}/calls", headers=as_user("owner"))
        ).status_code == 200
        assert (
            await client.get(f"{BASE}/calls", headers=as_user("academy"))
        ).status_code == 403

    async def test_a_call_from_another_tenant_is_not_found(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        """404 rather than 403: whether a call exists is itself the answer to a
        question this caller may not ask."""
        response = await client.get(
            f"{BASE}/calls/00000000-0000-7000-8000-000000000000",
            headers=as_user("owner"),
        )
        assert response.status_code == 404
