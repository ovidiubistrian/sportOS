"""Email marketing, and the consent that governs it.

The rule this file exists to defend: nobody is written to who has not asked to
hear from the club, and anybody who leaves is gone from the next send without
anybody remembering to prune a list. Everything else here — rendering, retry
safety — matters, but that one is the one a regulator asks about.

The sends are real: mailpit is in the stack, so a campaign in these tests goes
through the same SMTP path a club's would.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx
import pytest

pytestmark = pytest.mark.marketing

BASE = "/api/v1"
HOST = {"X-Forwarded-Host": "fcexample.localhost"}


def address(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}@example.com"


def signature(club_id: str, email: str) -> str:
    """The same HMAC the club's own email carries."""
    return hmac.new(
        b"dev-only-secret-not-for-any-other-use",
        f"{club_id}:{email.lower()}".encode(),
        hashlib.sha256,
    ).hexdigest()[:32]


@pytest.fixture
async def template(
    client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any], admin_engine: Any
) -> AsyncIterator[dict[str, Any]]:
    key = f"test-{uuid4().hex[:8]}"
    response = await client.post(
        f"{BASE}/email-templates",
        headers=as_user("owner"),
        json={
            "club_id": demo["club_id"],
            "key": key,
            "name": "Test letter",
            "subject": "Test subject",
            "preheader": "A line the inbox shows.",
            "blocks": [
                {"type": "paragraph", "text": "Salut <b>lume</b> & prieteni"},
                {"type": "list", "ordered": False, "items": ["Unu", "Doi"]},
            ],
            "cta_label": "Vezi",
            "cta_url": "http://fcexample.localhost/shop",
        },
    )
    assert response.status_code == 201, response.text
    created = response.json()
    try:
        yield created
    finally:
        from sqlalchemy import text

        async with admin_engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM campaign_recipient WHERE campaign_id IN "
                    "(SELECT id FROM campaign WHERE template_id = :t)"
                ),
                {"t": created["id"]},
            )
            await conn.execute(
                text("DELETE FROM campaign WHERE template_id = :t"), {"t": created["id"]}
            )
            await conn.execute(
                text("DELETE FROM email_template WHERE id = :t"), {"t": created["id"]}
            )


@pytest.fixture
async def subscriber(client: httpx.AsyncClient, admin_engine: Any) -> AsyncIterator[str]:
    email = address("abonat")
    response = await client.post(
        f"{BASE}/public/newsletter", headers=HOST, json={"email": email}
    )
    assert response.status_code in (201, 200), response.text
    try:
        yield email
    finally:
        from sqlalchemy import text

        async with admin_engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM newsletter_subscriber WHERE email = :e"), {"e": email}
            )


class TestConsent:
    async def test_a_subscriber_is_in_the_audience(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any], subscriber: str
    ) -> None:
        response = await client.get(
            f"{BASE}/campaigns/audience",
            headers=as_user("owner"),
            params={"club_id": demo["club_id"], "pool": "NEWSLETTER"},
        )
        assert response.status_code == 200
        assert response.json()["newsletter"] >= 1

    async def test_unsubscribing_removes_them_from_the_next_send(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any], subscriber: str
    ) -> None:
        """The audience is computed at send time, so leaving takes effect at once."""
        params = {"club_id": demo["club_id"], "pool": "NEWSLETTER"}
        before = (
            await client.get(
                f"{BASE}/campaigns/audience", headers=as_user("owner"), params=params
            )
        ).json()["total"]

        gone = await client.get(
            f"{BASE}/public/unsubscribe",
            headers=HOST,
            params={"e": subscriber, "t": signature(demo["club_id"], subscriber)},
        )
        assert gone.status_code == 204

        after = (
            await client.get(
                f"{BASE}/campaigns/audience", headers=as_user("owner"), params=params
            )
        ).json()["total"]
        assert after == before - 1

    async def test_a_forged_link_unsubscribes_nobody(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any], subscriber: str
    ) -> None:
        """And says so no more loudly than a real one would.

        A different answer for a bad signature would let somebody test whether
        an address is on a club's list.
        """
        params = {"club_id": demo["club_id"], "pool": "NEWSLETTER"}
        before = (
            await client.get(
                f"{BASE}/campaigns/audience", headers=as_user("owner"), params=params
            )
        ).json()["total"]

        forged = await client.get(
            f"{BASE}/public/unsubscribe",
            headers=HOST,
            params={"e": subscriber, "t": "0" * 32},
        )
        assert forged.status_code == 204

        after = (
            await client.get(
                f"{BASE}/campaigns/audience", headers=as_user("owner"), params=params
            )
        ).json()["total"]
        assert after == before

    async def test_a_token_from_one_club_does_not_work_at_another(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any], subscriber: str
    ) -> None:
        params = {"club_id": demo["club_id"], "pool": "NEWSLETTER"}
        before = (
            await client.get(
                f"{BASE}/campaigns/audience", headers=as_user("owner"), params=params
            )
        ).json()["total"]

        elsewhere = signature(demo["other_tenant_id"], subscriber)
        await client.get(
            f"{BASE}/public/unsubscribe", headers=HOST, params={"e": subscriber, "t": elsewhere}
        )

        after = (
            await client.get(
                f"{BASE}/campaigns/audience", headers=as_user("owner"), params=params
            )
        ).json()["total"]
        assert after == before


class TestTheLetter:
    async def test_what_an_author_types_never_becomes_markup(
        self, client: httpx.AsyncClient, as_user: Any, template: dict[str, Any]
    ) -> None:
        """The blocks are typed, so there is no route from text to HTML."""
        response = await client.get(
            f"{BASE}/email-templates/{template['id']}/preview", headers=as_user("owner")
        )
        assert response.status_code == 200
        html = response.json()["html"]
        assert "<b>lume</b>" not in html
        assert "&lt;b&gt;lume&lt;/b&gt;" in html

    async def test_it_carries_a_way_out(
        self, client: httpx.AsyncClient, as_user: Any, template: dict[str, Any]
    ) -> None:
        response = await client.get(
            f"{BASE}/email-templates/{template['id']}/preview", headers=as_user("owner")
        )
        body = response.json()
        assert "/dezabonare?" in body["html"]
        # And in the plain-text part, which is where a text-only client looks.
        assert "Dezabonare" in body["text"]

    async def test_there_is_always_a_plain_text_part(
        self, client: httpx.AsyncClient, as_user: Any, template: dict[str, Any]
    ) -> None:
        """A club's newsletter without one scores as spam."""
        body = (
            await client.get(
                f"{BASE}/email-templates/{template['id']}/preview", headers=as_user("owner")
            )
        ).json()
        assert body["text"].strip()
        assert "Salut" in body["text"]


class TestSending:
    async def test_a_campaign_reaches_the_people_who_agreed(
        self,
        client: httpx.AsyncClient,
        as_user: Any,
        demo: dict[str, Any],
        template: dict[str, Any],
        subscriber: str,
    ) -> None:
        campaign = await client.post(
            f"{BASE}/campaigns",
            headers=as_user("owner"),
            json={
                "club_id": demo["club_id"],
                "template_id": template["id"],
                "name": "Test campaign",
                "audience": "NEWSLETTER",
            },
        )
        assert campaign.status_code == 201, campaign.text

        sent = await client.post(
            f"{BASE}/campaigns/{campaign.json()['id']}/send", headers=as_user("owner")
        )
        assert sent.status_code == 200, sent.text
        body = sent.json()
        assert body["status"] == "SENT"
        assert body["sent"] >= 1
        assert body["failed"] == 0

    async def test_pressing_send_twice_reaches_nobody_twice(
        self,
        client: httpx.AsyncClient,
        as_user: Any,
        demo: dict[str, Any],
        template: dict[str, Any],
        subscriber: str,
    ) -> None:
        """The recipient list is written first, which is what makes this safe."""
        campaign = (
            await client.post(
                f"{BASE}/campaigns",
                headers=as_user("owner"),
                json={
                    "club_id": demo["club_id"],
                    "template_id": template["id"],
                    "name": "Test campaign twice",
                    "audience": "NEWSLETTER",
                },
            )
        ).json()

        first = await client.post(
            f"{BASE}/campaigns/{campaign['id']}/send", headers=as_user("owner")
        )
        assert first.status_code == 200

        again = await client.post(
            f"{BASE}/campaigns/{campaign['id']}/send", headers=as_user("owner")
        )
        assert again.status_code == 409

    async def test_a_campaign_with_nobody_to_write_to_is_refused(
        self,
        client: httpx.AsyncClient,
        as_user: Any,
        demo: dict[str, Any],
        template: dict[str, Any],
    ) -> None:
        """Better than reporting a successful send to an empty room."""
        campaign = (
            await client.post(
                f"{BASE}/campaigns",
                headers=as_user("owner"),
                json={
                    "club_id": demo["club_id"],
                    "template_id": template["id"],
                    "name": "Test empty",
                    "audience": "SUPPORTERS",
                    "locale": "zz",
                },
            )
        ).json()

        response = await client.post(
            f"{BASE}/campaigns/{campaign['id']}/send", headers=as_user("owner")
        )
        assert response.status_code == 422
