"""Sign-up.

The interesting cases are the ones that must not happen: a club taking a
reserved address, a second club taking the first one's, and — the one that
would need a human to fix — a tenant left with no owner.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.core.errors import ValidationFailed
from app.identity.registration import slugify, validate_password, validate_slug

pytestmark = pytest.mark.identity


@pytest.fixture(autouse=True)
async def _clear_rate_limits() -> None:
    """Sign-up allows five attempts an hour from one address.

    That is the right production number and the wrong one for a test file that
    makes eight requests in four seconds, so each test starts with the counters
    cleared. The limit itself is exercised deliberately in
    `test_the_rate_limit_actually_fires`.
    """
    from app.core.cache import cache

    keys = [key async for key in cache.client.scan_iter("signup:*")]
    if keys:
        await cache.delete(*keys)


class TestSlugs:
    def test_diacritics_are_folded_not_dropped(self) -> None:
        """A Romanian club should recognise its own address."""
        assert slugify("Știința București") == "stiinta-bucuresti"
        assert slugify("Universitatea Craiova") == "universitatea-craiova"

    def test_punctuation_and_spacing_collapse(self) -> None:
        assert slugify("  FC   Example!!  ") == "fc-example"
        assert slugify("A.C.S. Progresul") == "a-c-s-progresul"

    def test_reserved_words_are_refused(self) -> None:
        # A slug is a path on the platform host: `footbola.localhost/pricing`
        # must stay the pricing page.
        for reserved in ("pricing", "signin", "platform", "api", "admin", "settings"):
            with pytest.raises(ValidationFailed, match="reserved"):
                validate_slug(reserved)

    def test_shape_is_enforced(self) -> None:
        for bad in ("ab", "-leading", "trailing-", "Upper", "has space", "under_score"):
            with pytest.raises(ValidationFailed):
                validate_slug(bad)

    def test_a_normal_slug_passes(self) -> None:
        assert validate_slug("fc-example") == "fc-example"


class TestPasswords:
    def test_length_is_the_rule(self) -> None:
        with pytest.raises(ValidationFailed, match="12 characters"):
            validate_password("short")

    def test_a_passphrase_is_accepted(self) -> None:
        # No character-class rules: they push people towards `Password1!`,
        # which is weaker than this.
        assert validate_password("correct horse battery staple")


class TestSignUpRoute:
    async def test_languages_come_from_the_registry(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/api/v1/public/register/languages")
        assert response.status_code == 200
        codes = {item["code"] for item in response.json()}
        assert codes == {"en", "ro"}
        # Shown in the language itself — a speaker scans for their own word.
        assert any(item["endonym"] == "Română" for item in response.json())

    async def test_a_taken_address_is_reported_with_a_suggestion(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.get(
            "/api/v1/public/register/slug", params={"name": "FC Example"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["slug"] == "fc-example"
        assert body["available"] is False
        # Refusing without helping is how a sign-up form loses people.
        assert body["suggestion"]

    async def test_a_free_address_is_available(self, client: httpx.AsyncClient) -> None:
        response = await client.get(
            "/api/v1/public/register/slug",
            params={"name": "Clubul Sportiv Nimeni De Aici"},
        )
        assert response.json()["available"] is True

    async def test_a_reserved_address_is_never_available(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.get("/api/v1/public/register/slug", params={"name": "Pricing"})
        assert response.json()["available"] is False

    async def test_a_short_password_is_refused_before_anything_is_created(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/public/register",
            json={
                "email": "nobody@fcsignupprobe.com",
                "password": "short",
                "first_name": "A",
                "last_name": "B",
                "club_name": "Test Club",
                "slug": "test-club-refused",
                "country_code": "RO",
                "locale": "ro",
            },
        )
        assert response.status_code == 422

    async def test_an_unsupported_language_is_refused(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/api/v1/public/register",
            json={
                "email": "nobody2@fcsignupprobe.com",
                "password": "correct horse battery staple",
                "first_name": "A",
                "last_name": "B",
                "club_name": "Test Club",
                "slug": "test-club-de",
                "country_code": "DE",
                "locale": "de",
            },
        )
        assert response.status_code == 422

    async def test_a_reserved_slug_is_refused(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/api/v1/public/register",
            json={
                "email": "nobody3@fcsignupprobe.com",
                "password": "correct horse battery staple",
                "first_name": "A",
                "last_name": "B",
                "club_name": "Pricing",
                "slug": "pricing",
                "country_code": "RO",
                "locale": "ro",
            },
        )
        assert response.status_code == 422
        assert "reserved" in response.text.lower()


async def test_signing_up_creates_a_working_club(
    client: httpx.AsyncClient, admin_engine: Any
) -> None:
    """The whole path, against real Keycloak and real PostgreSQL.

    Cleaned up afterwards in both systems, because a test that leaves a tenant
    behind changes the answer of every count the next test makes.
    """
    from sqlalchemy import text

    from app.identity.keycloak import get_admin

    slug = "test-signup-club"
    email = "owner@fcsignupprobe.com"

    response = await client.post(
        "/api/v1/public/register",
        json={
            "email": email,
            "password": "correct horse battery staple",
            "first_name": "Ion",
            "last_name": "Popescu",
            "club_name": "Test Signup Club",
            "slug": slug,
            "country_code": "RO",
            "locale": "ro",
        },
    )

    subject_id: str | None = None
    try:
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["club_slug"] == slug
        assert body["verification_required"] is True

        async with admin_engine.connect() as conn:
            tenant = (
                await conn.execute(
                    text(
                        "SELECT status, default_locale, supported_locales, country_code "
                        "FROM tenant WHERE slug = :s"
                    ),
                    {"s": slug},
                )
            ).first()
            assert tenant is not None
            # PENDING until the address is proven: otherwise anyone could claim
            # a club's name with an email they do not control.
            assert tenant[0] == "PENDING"
            assert tenant[1] == "ro"
            assert tenant[2] == ["ro"]
            assert tenant[3] == "RO"

            owner = (
                await conn.execute(
                    text(
                        "SELECT ua.subject_id FROM role_assignment ra "
                        "JOIN user_account ua ON ua.id = ra.user_id "
                        "JOIN role r ON r.id = ra.role_id "
                        "JOIN tenant t ON t.id = ra.tenant_id "
                        "WHERE t.slug = :s AND r.key = 'TENANT_OWNER'"
                    ),
                    {"s": slug},
                )
            ).first()
            # The outcome this ordering exists to prevent: a club nobody can
            # sign into.
            assert owner is not None, "the tenant was created with no owner"
            subject_id = owner[0]

            club = (
                await conn.execute(
                    text("SELECT display_name FROM club WHERE slug = :s"), {"s": slug}
                )
            ).first()
            assert club is not None and club[0] == "Test Signup Club"
    finally:
        if subject_id:
            await get_admin().delete_user(subject_id)
        async with admin_engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM role_assignment WHERE tenant_id IN "
                    "(SELECT id FROM tenant WHERE slug = :s)"
                ),
                {"s": slug},
            )
            # In dependency order. `club.tenant_id` is RESTRICT on purpose —
            # deleting a tenant that still has clubs would be silent data loss,
            # so the test has to unwind the same way an operator would.
            await conn.execute(
                text(
                    "DELETE FROM club_branding WHERE tenant_id IN "
                    "(SELECT id FROM tenant WHERE slug = :s)"
                ),
                {"s": slug},
            )
            await conn.execute(text("DELETE FROM club WHERE slug = :s"), {"s": slug})
            await conn.execute(
                text(
                    "DELETE FROM person WHERE tenant_id IN "
                    "(SELECT id FROM tenant WHERE slug = :s)"
                ),
                {"s": slug},
            )
            await conn.execute(text("DELETE FROM tenant WHERE slug = :s"), {"s": slug})
            await conn.execute(text("DELETE FROM user_account WHERE email = :e"), {"e": email})


async def test_the_rate_limit_actually_fires(client: httpx.AsyncClient) -> None:
    """Sign-up is the most exposed write path in the product.

    Without this, one script creates a thousand tenants and takes a thousand
    club addresses with it.
    """
    # A reserved slug, so every attempt is refused before anything is created.
    # That is only possible because the limiter runs *before* validation — which
    # is the correct order: a flood of invalid requests is still a flood.
    payload = {
        "email": "flood@fcsignupprobe.com",
        "password": "correct horse battery staple",
        "first_name": "A",
        "last_name": "B",
        "club_name": "Pricing",
        "slug": "pricing",
        "country_code": "RO",
        "locale": "ro",
    }

    statuses = [
        (await client.post("/api/v1/public/register", json=payload)).status_code
        for _ in range(8)
    ]

    assert 429 in statuses, f"the limit never fired: {statuses}"
    assert statuses.index(429) <= 5, statuses


async def test_a_new_club_gets_an_address_it_can_be_reached_on(
    client: httpx.AsyncClient, admin_engine: Any
) -> None:
    """A club with no domain has no website.

    The domain is issued during sign-up rather than left as a later step,
    because a club that has just paid attention long enough to register should
    not then have to discover that its site exists at no address.
    """
    from sqlalchemy import text

    from app.identity.keycloak import get_admin

    slug = "test-domain-club"
    email = "owner@fcdomainprobe.com"

    response = await client.post(
        "/api/v1/public/register",
        json={
            "email": email,
            "password": "correct horse battery staple",
            "first_name": "Ion",
            "last_name": "Popescu",
            "club_name": "Test Domain Club",
            "slug": slug,
            "country_code": "RO",
            "locale": "ro",
        },
    )

    subject_id: str | None = None
    try:
        assert response.status_code == 201, response.text

        async with admin_engine.connect() as conn:
            domain = (
                await conn.execute(
                    text(
                        "SELECT d.hostname, d.verification_status FROM club_domain d "
                        "JOIN club c ON c.id = d.club_id WHERE c.slug = :s"
                    ),
                    {"s": slug},
                )
            ).first()
            assert domain is not None, "the club was created with no address"
            assert domain[0] == f"{slug}.localhost"

            owner = (
                await conn.execute(
                    text(
                        "SELECT ua.subject_id FROM role_assignment ra "
                        "JOIN user_account ua ON ua.id = ra.user_id "
                        "JOIN tenant t ON t.id = ra.tenant_id WHERE t.slug = :s"
                    ),
                    {"s": slug},
                )
            ).first()
            subject_id = owner[0] if owner else None
    finally:
        if subject_id:
            await get_admin().delete_user(subject_id)
        async with admin_engine.begin() as conn:
            for statement in (
                "DELETE FROM role_assignment WHERE tenant_id IN "
                "(SELECT id FROM tenant WHERE slug = :s)",
                "DELETE FROM club_branding WHERE tenant_id IN "
                "(SELECT id FROM tenant WHERE slug = :s)",
                "DELETE FROM club_domain WHERE tenant_id IN "
                "(SELECT id FROM tenant WHERE slug = :s)",
                "DELETE FROM club WHERE slug = :s",
                "DELETE FROM person WHERE tenant_id IN (SELECT id FROM tenant WHERE slug = :s)",
                "DELETE FROM tenant_subscription WHERE tenant_id IN "
                "(SELECT id FROM tenant WHERE slug = :s)",
                "DELETE FROM user_account WHERE email = :e",
                "DELETE FROM tenant WHERE slug = :s",
            ):
                await conn.execute(text(statement), {"s": slug, "e": email})
