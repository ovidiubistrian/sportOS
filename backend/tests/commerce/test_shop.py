"""The club shop, from both sides.

The supporter's half is unauthenticated and identified only by a cart token, so
the assertions that matter are about what a token does and does not get you: a
basket is scoped to the club whose shop filled it, and a token is not a session.

The club's half is ordinary CRUD with one rule worth testing — stock. Two people
buying the last scarf must not both succeed, and a cancelled order has to put it
back on the shelf.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx
import pytest

pytestmark = pytest.mark.commerce

BASE = "/api/v1"
HOST = {"X-Forwarded-Host": "fcexample.localhost"}
# A second tenant's website, for the scoping tests. It must be one the demo
# seed actually creates: an earlier version of these tests pointed at a club
# that existed only in one developer's database, so they passed there and
# nowhere else.
OTHER_HOST = "northern.localhost"


def unique(prefix: str) -> str:
    return f"{prefix} {uuid4().hex[:8]}"


@pytest.fixture
async def product(
    client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
) -> AsyncIterator[dict[str, Any]]:
    response = await client.post(
        f"{BASE}/products",
        headers=as_user("owner"),
        json={
            "club_id": demo["club_id"],
            "name": unique("Test Scarf"),
            "description": "Knitted in the club's colours.",
            "price_minor": 12_00,
            "variants": [
                {"label": "One size", "stock": 3, "sku": "SCARF-1"},
            ],
        },
    )
    assert response.status_code == 201, response.text
    created = response.json()
    try:
        yield created
    finally:
        # Cancel anything still pending, so the product can be deleted and the
        # demo shop does not fill with a season of test scarves.
        orders = (
            await client.get(
                f"{BASE}/orders",
                headers=as_user("owner"),
                params={"club_id": demo["club_id"], "status": "AWAITING_COLLECTION"},
            )
        ).json()
        variant_ids = {v["id"] for v in created["variants"]}
        for order in orders:
            if any(line["description"].startswith(created["name"]) for line in order["lines"]):
                await client.post(
                    f"{BASE}/orders/{order['id']}/status",
                    headers=as_user("owner"),
                    params={"club_id": demo["club_id"]},
                    json={"status": "CANCELLED"},
                )
        assert variant_ids
        await client.delete(f"{BASE}/products/{created['id']}", headers=as_user("owner"))


async def basket_with(
    client: httpx.AsyncClient, variant_id: str, quantity: int = 1, token: str | None = None
) -> dict[str, Any]:
    headers = dict(HOST)
    if token:
        headers["X-Cart-Token"] = token
    response = await client.put(
        f"{BASE}/public/basket/lines",
        headers=headers,
        json={"variant_id": variant_id, "quantity": quantity},
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestTheCatalogue:
    async def test_a_product_gets_a_variant_even_without_sizes(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        """Stock lives on the variant, so every product needs one."""
        response = await client.post(
            f"{BASE}/products",
            headers=as_user("owner"),
            json={
                "club_id": demo["club_id"],
                "name": unique("Sizeless Thing"),
                "price_minor": 500,
                "variants": [],
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert [v["label"] for v in body["variants"]] == ["One size"]
        await client.delete(f"{BASE}/products/{body['id']}", headers=as_user("owner"))

    async def test_variants_are_matched_by_id_not_position(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        """Reordering sizes must not move the stock count onto another size."""
        created = (
            await client.post(
                f"{BASE}/products",
                headers=as_user("owner"),
                json={
                    "club_id": demo["club_id"],
                    "name": unique("Shirt"),
                    "price_minor": 45_00,
                    "variants": [
                        {"label": "M", "stock": 4},
                        {"label": "L", "stock": 9},
                    ],
                },
            )
        ).json()
        by_label = {v["label"]: v for v in created["variants"]}

        reordered = await client.patch(
            f"{BASE}/products/{created['id']}",
            headers=as_user("owner"),
            json={
                "variants": [
                    {"id": by_label["L"]["id"], "label": "L", "stock": 9, "sort_order": 0},
                    {"id": by_label["M"]["id"], "label": "M", "stock": 4, "sort_order": 1},
                ]
            },
        )
        assert reordered.status_code == 200, reordered.text
        after = {v["label"]: v["stock"] for v in reordered.json()["variants"]}
        assert after == {"M": 4, "L": 9}

        await client.delete(f"{BASE}/products/{created['id']}", headers=as_user("owner"))

    async def test_a_duplicate_name_is_refused(
        self,
        client: httpx.AsyncClient,
        as_user: Any,
        demo: dict[str, Any],
        product: dict[str, Any],
    ) -> None:
        response = await client.post(
            f"{BASE}/products",
            headers=as_user("owner"),
            json={
                "club_id": demo["club_id"],
                "name": product["name"],
                "price_minor": 100,
            },
        )
        assert response.status_code == 409

    async def test_a_coach_cannot_add_a_product(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        response = await client.post(
            f"{BASE}/products",
            headers=as_user("coach"),
            json={
                "club_id": demo["club_id"],
                "name": unique("Coach Merch"),
                "price_minor": 100,
            },
        )
        assert response.status_code in (403, 404)

    async def test_another_tenant_cannot_edit_our_product(
        self, client: httpx.AsyncClient, as_user: Any, product: dict[str, Any]
    ) -> None:
        """Refused, and the price is untouched.

        Which refusal is not the point and is deliberately not asserted: the
        other tenant is on a plan without a shop, so entitlement answers before
        tenancy gets a chance to. Both are correct; pinning one would make this
        test fail the day someone upgrades a fixture's plan.
        """
        response = await client.patch(
            f"{BASE}/products/{product['id']}",
            headers=as_user("other_owner"),
            json={"price_minor": 1},
        )
        assert response.status_code in (402, 403, 404)

        after = (
            await client.get(
                f"{BASE}/products",
                headers=as_user("owner"),
                params={"club_id": product["club_id"]},
            )
        ).json()
        ours = next(row for row in after if row["id"] == product["id"])
        assert ours["price_minor"] == product["price_minor"]


class TestTheShopWindow:
    async def test_a_hidden_product_is_not_on_the_public_shop(
        self, client: httpx.AsyncClient, as_user: Any, product: dict[str, Any]
    ) -> None:
        listed = (await client.get(f"{BASE}/public/shop", headers=HOST)).json()
        assert product["id"] in {row["id"] for row in listed}

        await client.patch(
            f"{BASE}/products/{product['id']}",
            headers=as_user("owner"),
            json={"is_active": False},
        )
        hidden = (await client.get(f"{BASE}/public/shop", headers=HOST)).json()
        assert product["id"] not in {row["id"] for row in hidden}

        await client.patch(
            f"{BASE}/products/{product['id']}",
            headers=as_user("owner"),
            json={"is_active": True},
        )

    async def test_the_shop_is_scoped_to_the_host(
        self, client: httpx.AsyncClient, product: dict[str, Any]
    ) -> None:
        """No club parameter anywhere — the domain decides whose shop this is."""
        ours = (await client.get(f"{BASE}/public/shop", headers=HOST)).json()
        theirs = (
            await client.get(
                f"{BASE}/public/shop", headers={"X-Forwarded-Host": OTHER_HOST}
            )
        ).json()
        assert product["id"] in {row["id"] for row in ours}
        assert product["id"] not in {row["id"] for row in theirs}


class TestTheBasket:
    async def test_a_line_is_set_not_added(
        self, client: httpx.AsyncClient, product: dict[str, Any]
    ) -> None:
        """A double-tapped button must not order two scarves."""
        variant = product["variants"][0]["id"]
        first = await basket_with(client, variant, 1)
        again = await basket_with(client, variant, 1, token=first["token"])
        assert [line["quantity"] for line in again["lines"]] == [1]

    async def test_zero_removes_the_line(
        self, client: httpx.AsyncClient, product: dict[str, Any]
    ) -> None:
        variant = product["variants"][0]["id"]
        basket = await basket_with(client, variant, 2)
        emptied = await basket_with(client, variant, 0, token=basket["token"])
        assert emptied["lines"] == []
        assert emptied["total_minor"] == 0

    async def test_more_than_the_shelf_holds_is_refused_in_the_basket(
        self, client: httpx.AsyncClient, product: dict[str, Any]
    ) -> None:
        """Refused now, not at checkout — the buyer has filled in no form yet."""
        response = await client.put(
            f"{BASE}/public/basket/lines",
            headers=HOST,
            json={"variant_id": product["variants"][0]["id"], "quantity": 4},
        )
        assert response.status_code == 422
        assert "3" in response.text

    async def test_a_token_from_one_club_does_not_open_a_basket_at_another(
        self, client: httpx.AsyncClient, product: dict[str, Any]
    ) -> None:
        basket = await basket_with(client, product["variants"][0]["id"], 1)

        elsewhere = (
            await client.get(
                f"{BASE}/public/basket",
                headers={
                    "X-Forwarded-Host": OTHER_HOST,
                    "X-Cart-Token": basket["token"],
                },
            )
        ).json()
        assert elsewhere["lines"] == []
        assert elsewhere["token"] != basket["token"], "a fresh basket, not the other club's"


class TestCheckout:
    async def test_an_order_takes_the_stock_and_can_be_collected(
        self,
        client: httpx.AsyncClient,
        as_user: Any,
        demo: dict[str, Any],
        product: dict[str, Any],
    ) -> None:
        variant = product["variants"][0]["id"]
        basket = await basket_with(client, variant, 2)

        placed = await client.post(
            f"{BASE}/public/basket/checkout",
            headers={**HOST, "X-Cart-Token": basket["token"]},
            json={"name": "Ion Popescu", "email": "ion@example.com"},
        )
        assert placed.status_code == 201, placed.text
        order = placed.json()
        assert order["total_minor"] == 24_00
        assert len(order["reference"]) == 8
        assert order["lines"][0]["quantity"] == 2

        shop = (await client.get(f"{BASE}/public/shop", headers=HOST)).json()
        remaining = next(
            v["stock"]
            for row in shop
            if row["id"] == product["id"]
            for v in row["variants"]
            if v["id"] == variant
        )
        assert remaining == 1, "two of three sold"

        orders = (
            await client.get(
                f"{BASE}/orders", headers=as_user("owner"), params={"club_id": demo["club_id"]}
            )
        ).json()
        ours = next(row for row in orders if row["reference"] == order["reference"])
        assert ours["status"] == "AWAITING_COLLECTION"
        assert ours["buyer_name"] == "Ion Popescu"

        collected = await client.post(
            f"{BASE}/orders/{ours['id']}/status",
            headers=as_user("owner"),
            params={"club_id": demo["club_id"]},
            json={"status": "COLLECTED"},
        )
        assert collected.status_code == 200
        assert collected.json()["status"] == "COLLECTED"

    async def test_the_last_one_can_only_be_sold_once(
        self, client: httpx.AsyncClient, product: dict[str, Any]
    ) -> None:
        """Two baskets, three in stock, two each. The second must fail."""
        variant = product["variants"][0]["id"]
        first = await basket_with(client, variant, 2)
        second = await basket_with(client, variant, 2)
        assert first["token"] != second["token"]

        one = await client.post(
            f"{BASE}/public/basket/checkout",
            headers={**HOST, "X-Cart-Token": first["token"]},
            json={"name": "First Buyer"},
        )
        assert one.status_code == 201, one.text

        two = await client.post(
            f"{BASE}/public/basket/checkout",
            headers={**HOST, "X-Cart-Token": second["token"]},
            json={"name": "Second Buyer"},
        )
        assert two.status_code == 422, "only one left; two were asked for"

    async def test_cancelling_puts_the_stock_back(
        self,
        client: httpx.AsyncClient,
        as_user: Any,
        demo: dict[str, Any],
        product: dict[str, Any],
    ) -> None:
        variant = product["variants"][0]["id"]
        basket = await basket_with(client, variant, 3)
        placed = (
            await client.post(
                f"{BASE}/public/basket/checkout",
                headers={**HOST, "X-Cart-Token": basket["token"]},
                json={"name": "Changed Mind"},
            )
        ).json()

        sold_out = (await client.get(f"{BASE}/public/shop", headers=HOST)).json()
        assert all(
            v["stock"] == 0
            for row in sold_out
            if row["id"] == product["id"]
            for v in row["variants"]
        )

        orders = (
            await client.get(
                f"{BASE}/orders", headers=as_user("owner"), params={"club_id": demo["club_id"]}
            )
        ).json()
        ours = next(row for row in orders if row["reference"] == placed["reference"])
        cancelled = await client.post(
            f"{BASE}/orders/{ours['id']}/status",
            headers=as_user("owner"),
            params={"club_id": demo["club_id"]},
            json={"status": "CANCELLED"},
        )
        assert cancelled.status_code == 200

        restocked = (await client.get(f"{BASE}/public/shop", headers=HOST)).json()
        assert any(
            v["stock"] == 3
            for row in restocked
            if row["id"] == product["id"]
            for v in row["variants"]
        )

    async def test_a_basket_cannot_be_checked_out_twice(
        self, client: httpx.AsyncClient, product: dict[str, Any]
    ) -> None:
        basket = await basket_with(client, product["variants"][0]["id"], 1)
        first = await client.post(
            f"{BASE}/public/basket/checkout",
            headers={**HOST, "X-Cart-Token": basket["token"]},
            json={"name": "Double Tapper"},
        )
        assert first.status_code == 201

        second = await client.post(
            f"{BASE}/public/basket/checkout",
            headers={**HOST, "X-Cart-Token": basket["token"]},
            json={"name": "Double Tapper"},
        )
        assert second.status_code == 404, "the cart was converted, not left open"

    async def test_an_empty_basket_is_refused(self, client: httpx.AsyncClient) -> None:
        basket = (await client.get(f"{BASE}/public/basket", headers=HOST)).json()
        response = await client.post(
            f"{BASE}/public/basket/checkout",
            headers={**HOST, "X-Cart-Token": basket["token"]},
            json={"name": "Nobody"},
        )
        assert response.status_code == 422

    async def test_a_product_awaiting_collection_cannot_be_deleted(
        self,
        client: httpx.AsyncClient,
        as_user: Any,
        demo: dict[str, Any],
        product: dict[str, Any],
    ) -> None:
        """Someone is coming to the counter for it."""
        basket = await basket_with(client, product["variants"][0]["id"], 1)
        await client.post(
            f"{BASE}/public/basket/checkout",
            headers={**HOST, "X-Cart-Token": basket["token"]},
            json={"name": "Waiting Buyer"},
        )

        response = await client.delete(
            f"{BASE}/products/{product['id']}", headers=as_user("owner")
        )
        assert response.status_code == 409
