"""Supporter accounts: one login, a separate relationship with each club.

The interesting assertions are all about that separation. A supporter is
identified by their token but *scoped* by the domain they arrived on, so the
same person signing in at two clubs must get two accounts and must never see
one club's purchases on the other's site.

The account is also deliberately not a staff membership. The user driving most
of these tests owns a different tenant entirely and has no rights at all in
this one — which is exactly the point: being a supporter of a club and being
able to administer it are unrelated facts.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx
import pytest

pytestmark = pytest.mark.fans

BASE = "/api/v1"
HOST = {"X-Forwarded-Host": "fcexample.localhost"}
OTHER_HOST = {"X-Forwarded-Host": "northern.localhost"}


def unique(prefix: str) -> str:
    return f"{prefix} {uuid4().hex[:8]}"


@pytest.fixture
async def supporter(client: httpx.AsyncClient, as_user: Any) -> AsyncIterator[dict[str, str]]:
    """A signed-in visitor to fcexample, cleaned up afterwards.

    `other_owner` runs a different club and holds nothing here; using them
    proves the account is created from the login alone.
    """
    headers = {**HOST, **as_user("other_owner")}
    response = await client.get(f"{BASE}/public/account", headers=headers)
    assert response.status_code == 200, response.text
    try:
        yield headers
    finally:
        await client.delete(f"{BASE}/public/account", headers=headers)
        await client.delete(
            f"{BASE}/public/account", headers={**OTHER_HOST, **as_user("other_owner")}
        )


@pytest.fixture
async def scarf(
    client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
) -> AsyncIterator[dict[str, Any]]:
    created = (
        await client.post(
            f"{BASE}/products",
            headers=as_user("owner"),
            json={
                "club_id": demo["club_id"],
                "name": unique("Supporter Scarf"),
                "price_minor": 10_00,
                "variants": [{"label": "One size", "stock": 5}],
            },
        )
    ).json()
    try:
        yield created
    finally:
        orders = (
            await client.get(
                f"{BASE}/orders",
                headers=as_user("owner"),
                params={"club_id": demo["club_id"], "status": "AWAITING_COLLECTION"},
            )
        ).json()
        for order in orders:
            if any(line["description"].startswith(created["name"]) for line in order["lines"]):
                await client.post(
                    f"{BASE}/orders/{order['id']}/status",
                    headers=as_user("owner"),
                    params={"club_id": demo["club_id"]},
                    json={"status": "CANCELLED"},
                )
        await client.delete(f"{BASE}/products/{created['id']}", headers=as_user("owner"))


async def buy(
    client: httpx.AsyncClient, variant_id: str, headers: dict[str, str]
) -> dict[str, Any]:
    """Fill a basket and check out, as whoever `headers` says."""
    basket = await client.put(
        f"{BASE}/public/basket/lines",
        headers=headers,
        json={"variant_id": variant_id, "quantity": 1},
    )
    assert basket.status_code == 200, basket.text
    token = basket.json()["token"]

    placed = await client.post(
        f"{BASE}/public/basket/checkout",
        headers={**headers, "X-Cart-Token": token},
        json={"name": "Test Supporter", "email": "supporter@example.com"},
    )
    assert placed.status_code == 201, placed.text
    return placed.json()


class TestSigningIn:
    async def test_an_unauthenticated_visitor_has_no_account(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.get(f"{BASE}/public/account", headers=HOST)
        assert response.status_code == 401

    async def test_a_bad_token_is_not_a_session(self, client: httpx.AsyncClient) -> None:
        response = await client.get(
            f"{BASE}/public/account",
            headers={**HOST, "Authorization": "Bearer not-a-token"},
        )
        assert response.status_code == 401

    async def test_signing_in_creates_the_relationship(
        self, client: httpx.AsyncClient, supporter: dict[str, str]
    ) -> None:
        """No separate "join the club" step: arriving signed in is enough."""
        body = (await client.get(f"{BASE}/public/account", headers=supporter)).json()
        assert body["display_name"]
        assert body["marketing_opt_in"] is False

    async def test_the_account_is_never_cached(
        self, client: httpx.AsyncClient, supporter: dict[str, str]
    ) -> None:
        response = await client.get(f"{BASE}/public/account", headers=supporter)
        assert response.headers["cache-control"] == "no-store"


class TestDetails:
    async def test_a_supporter_can_correct_their_own_details(
        self, client: httpx.AsyncClient, supporter: dict[str, str]
    ) -> None:
        response = await client.put(
            f"{BASE}/public/account",
            headers=supporter,
            json={"display_name": "Ovidiu B", "phone": "+40 700 000 000"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["display_name"] == "Ovidiu B"

        again = (await client.get(f"{BASE}/public/account", headers=supporter)).json()
        assert again["phone"] == "+40 700 000 000"

    async def test_marketing_consent_is_off_until_it_is_given(
        self, client: httpx.AsyncClient, supporter: dict[str, str]
    ) -> None:
        """Having an account is not agreeing to be emailed."""
        opted_in = await client.put(
            f"{BASE}/public/account", headers=supporter, json={"marketing_opt_in": True}
        )
        assert opted_in.json()["marketing_opt_in"] is True

        withdrawn = await client.put(
            f"{BASE}/public/account", headers=supporter, json={"marketing_opt_in": False}
        )
        assert withdrawn.json()["marketing_opt_in"] is False


class TestOrderHistory:
    async def test_a_signed_in_purchase_lands_in_the_account(
        self,
        client: httpx.AsyncClient,
        supporter: dict[str, str],
        scarf: dict[str, Any],
    ) -> None:
        placed = await buy(client, scarf["variants"][0]["id"], supporter)

        orders = (await client.get(f"{BASE}/public/account/orders", headers=supporter)).json()
        assert placed["reference"] in [order["reference"] for order in orders]

        mine = next(o for o in orders if o["reference"] == placed["reference"])
        assert mine["total_minor"] == 10_00
        assert mine["lines"][0]["quantity"] == 1

    async def test_a_guest_purchase_belongs_to_nobody(
        self,
        client: httpx.AsyncClient,
        supporter: dict[str, str],
        scarf: dict[str, Any],
    ) -> None:
        """Buying without signing in must not attach to an account by email.

        The guest here gives the same email the account uses, which is the whole
        risk: matching on an address would hand somebody's purchase history to
        anybody who could guess it.
        """
        placed = await buy(client, scarf["variants"][0]["id"], dict(HOST))

        orders = (await client.get(f"{BASE}/public/account/orders", headers=supporter)).json()
        assert placed["reference"] not in [order["reference"] for order in orders]

    async def test_one_club_cannot_see_anothers_purchases(
        self,
        client: httpx.AsyncClient,
        as_user: Any,
        supporter: dict[str, str],
        scarf: dict[str, Any],
    ) -> None:
        """The same login, a different domain, a different account."""
        placed = await buy(client, scarf["variants"][0]["id"], supporter)

        elsewhere = {**OTHER_HOST, **as_user("other_owner")}
        assert (
            await client.get(f"{BASE}/public/account", headers=elsewhere)
        ).status_code == 200

        orders = (await client.get(f"{BASE}/public/account/orders", headers=elsewhere)).json()
        assert placed["reference"] not in [order["reference"] for order in orders]


class TestClosingTheAccount:
    async def test_closing_leaves_the_clubs_records_intact(
        self,
        client: httpx.AsyncClient,
        as_user: Any,
        demo: dict[str, Any],
        supporter: dict[str, str],
        scarf: dict[str, Any],
    ) -> None:
        """The order is the club's record; the link to a person is not."""
        placed = await buy(client, scarf["variants"][0]["id"], supporter)

        closed = await client.delete(f"{BASE}/public/account", headers=supporter)
        assert closed.status_code == 204

        # The club still has the sale.
        orders = (
            await client.get(
                f"{BASE}/orders",
                headers=as_user("owner"),
                params={"club_id": demo["club_id"], "status": "AWAITING_COLLECTION"},
            )
        ).json()
        assert placed["reference"] in [order["reference"] for order in orders]

        # Signing in again is a fresh relationship, with no history attached.
        reopened = await client.get(f"{BASE}/public/account", headers=supporter)
        assert reopened.status_code == 200
        assert (
            await client.get(f"{BASE}/public/account/orders", headers=supporter)
        ).json() == []
