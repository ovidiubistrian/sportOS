"""Host-based club resolution.

The rule under test: a club is identified by the domain the visitor arrived on
and nothing else. An unknown host is a 404, never a fallback club — serving one
club's content on another club's domain is the worst failure this module can
have.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.tenants.site_service import normalise_host

pytestmark = pytest.mark.branding


class TestHostNormalisation:
    @pytest.mark.parametrize(
        ("given", "expected"),
        [
            ("FCExample.localhost", "fcexample.localhost"),
            ("fcexample.localhost:3000", "fcexample.localhost"),
            ("fcexample.localhost.", "fcexample.localhost"),
            ("  fcexample.localhost  ", "fcexample.localhost"),
        ],
    )
    def test_normalises(self, given: str, expected: str) -> None:
        assert normalise_host(given) == expected

    @pytest.mark.parametrize("given", [None, "", "   ", "[::1]"])
    def test_rejects_unusable_hosts(self, given: str | None) -> None:
        assert normalise_host(given) is None


class TestCertificateGuard:
    """The `ask` endpoint Caddy calls before issuing a certificate."""

    async def test_known_domain_is_allowed(self, client: httpx.AsyncClient) -> None:
        response = await client.get(
            "/api/v1/public/domains/check", params={"domain": "fcexample.localhost"}
        )
        assert response.status_code == 200

    async def test_unknown_domain_is_refused(self, client: httpx.AsyncClient) -> None:
        """Without this, anyone pointing DNS at us could exhaust our CA rate limit."""
        for domain in ("squatter.example.com", "not-a-club.test", "footbola.io.evil.com"):
            response = await client.get(
                "/api/v1/public/domains/check", params={"domain": domain}
            )
            assert response.status_code == 404, f"{domain} would have been issued a certificate"


class TestSiteResolution:
    async def test_each_host_returns_its_own_club(self, client: httpx.AsyncClient) -> None:
        first = await client.get(
            "/api/v1/public/site", headers={"X-Forwarded-Host": "fcexample.localhost"}
        )
        second = await client.get(
            "/api/v1/public/site", headers={"X-Forwarded-Host": "northern.localhost"}
        )

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["name"] == "FC Example"
        assert second.json()["name"] == "Northern United"
        assert first.json()["club_id"] != second.json()["club_id"]

    async def test_each_host_gets_its_own_template_and_palette(
        self, client: httpx.AsyncClient
    ) -> None:
        first = (
            await client.get(
                "/api/v1/public/site", headers={"X-Forwarded-Host": "fcexample.localhost"}
            )
        ).json()["branding"]
        second = (
            await client.get(
                "/api/v1/public/site", headers={"X-Forwarded-Host": "northern.localhost"}
            )
        ).json()["branding"]

        assert first["template"] != second["template"]
        assert first["color_primary"] != second["color_primary"]
        assert first["palette"]["--brand"] == first["color_primary"]
        # Derived, so the site never has to work out readable text itself.
        assert "--brand-contrast" in first["palette"]
        assert "--brand-text" in first["palette"]

    async def test_unknown_host_is_not_found(self, client: httpx.AsyncClient) -> None:
        response = await client.get(
            "/api/v1/public/site", headers={"X-Forwarded-Host": "nobody.localhost"}
        )
        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"

    async def test_teams_are_scoped_to_the_host(self, client: httpx.AsyncClient) -> None:
        first = await client.get(
            "/api/v1/public/teams", headers={"X-Forwarded-Host": "fcexample.localhost"}
        )
        second = await client.get(
            "/api/v1/public/teams", headers={"X-Forwarded-Host": "northern.localhost"}
        )
        assert len(first.json()) == 12
        assert len(second.json()) == 1

    async def test_a_squad_from_another_club_is_not_found(
        self, client: httpx.AsyncClient
    ) -> None:
        """Cross-club object access through the public API, via a guessed id."""
        teams = (
            await client.get(
                "/api/v1/public/teams", headers={"X-Forwarded-Host": "fcexample.localhost"}
            )
        ).json()
        foreign_team_id = teams[0]["id"]

        response = await client.get(
            f"/api/v1/public/teams/{foreign_team_id}/squad",
            headers={"X-Forwarded-Host": "northern.localhost"},
        )
        assert response.status_code == 404

    async def test_squads_omit_personal_data(self, client: httpx.AsyncClient) -> None:
        """Publishing a minor's birth date next to their name and club is a
        safeguarding problem, not a feature.

        An exact set rather than a subset, so this fails whenever the payload
        grows and somebody has to decide again. A squad photograph passed that
        decision — the club uploads it deliberately, one player at a time — and
        a date of birth never will.
        """
        teams = (
            await client.get(
                "/api/v1/public/teams", headers={"X-Forwarded-Host": "fcexample.localhost"}
            )
        ).json()
        squad = await client.get(
            f"/api/v1/public/teams/{teams[0]['id']}/squad",
            headers={"X-Forwarded-Host": "fcexample.localhost"},
        )
        assert squad.status_code == 200
        rows = squad.json()
        assert rows, "expected a seeded squad"
        for player in rows:
            assert set(player) == {"id", "name", "shirt_number", "position", "photo_url"}

    async def test_public_responses_are_cacheable(self, client: httpx.AsyncClient) -> None:
        response = await client.get(
            "/api/v1/public/site", headers={"X-Forwarded-Host": "fcexample.localhost"}
        )
        assert "public" in response.headers.get("cache-control", "")

    async def test_authenticated_routes_are_never_publicly_cacheable(
        self, client: httpx.AsyncClient, as_user: Any
    ) -> None:
        response = await client.get("/api/v1/me", headers=as_user("owner"))
        assert response.headers.get("cache-control") == "no-store"


class TestBrandingApi:
    async def test_a_club_admin_can_read_and_change_the_design(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        club_id = demo["club_id"]
        original = await client.get(
            f"/api/v1/clubs/{club_id}/branding", headers=as_user("owner")
        )
        assert original.status_code == 200
        before = original.json()

        try:
            updated = await client.put(
                f"/api/v1/clubs/{club_id}/branding",
                headers=as_user("owner"),
                json={"template": "EDITORIAL", "color_primary": "#FFE600"},
            )
            assert updated.status_code == 200
            body = updated.json()
            assert body["template"] == "EDITORIAL"
            assert body["color_primary"] == "#FFE600"
            # A light brand colour is accepted, and the readable variant is
            # derived rather than the club being told "no".
            assert body["checks"]["primary"]["meets_aa_as_text"] is False
            assert body["checks"]["primary"]["was_adjusted"] is True
            assert body["checks"]["primary"]["advice"]
            assert body["palette"]["--brand-contrast"] == "#000000"
        finally:
            await client.put(
                f"/api/v1/clubs/{club_id}/branding",
                headers=as_user("owner"),
                json={
                    "template": before["template"],
                    "color_primary": before["color_primary"],
                },
            )

    async def test_an_invalid_colour_is_rejected(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        response = await client.put(
            f"/api/v1/clubs/{demo['club_id']}/branding",
            headers=as_user("owner"),
            json={"color_primary": "octarine"},
        )
        assert response.status_code == 422

    async def test_an_unknown_template_is_rejected(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        """Templates are a closed set; a club cannot supply its own."""
        response = await client.put(
            f"/api/v1/clubs/{demo['club_id']}/branding",
            headers=as_user("owner"),
            json={"template": "CUSTOM"},
        )
        assert response.status_code == 422

    async def test_a_coach_cannot_change_the_design(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        response = await client.put(
            f"/api/v1/clubs/{demo['club_id']}/branding",
            headers=as_user("coach"),
            json={"template": "BOLD"},
        )
        assert response.status_code == 403

    async def test_another_tenant_cannot_read_the_design(
        self, client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
    ) -> None:
        response = await client.get(
            f"/api/v1/clubs/{demo['club_id']}/branding", headers=as_user("other_owner")
        )
        assert response.status_code == 404


class TestTheCertificateGate:
    """What the proxy asks before obtaining a certificate for a hostname.

    Club domains are created while the server runs, so certificates cannot be
    listed in configuration and are issued on demand. This endpoint is the only
    thing standing between that and a stranger pointing a DNS record at the
    server to have their domain served by us — or simply to burn through the
    certificate authority's rate limit on our account.
    """

    async def test_a_club_domain_is_allowed(self, client: httpx.AsyncClient) -> None:
        response = await client.get(
            "/api/v1/public/tls-check", params={"domain": "fcexample.localhost"}
        )
        assert response.status_code == 204

    async def test_a_domain_nobody_owns_here_is_refused(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.get(
            "/api/v1/public/tls-check", params={"domain": "not-our-domain.example.com"}
        )
        assert response.status_code == 404

    async def test_the_answer_is_never_cached(self, client: httpx.AsyncClient) -> None:
        """A club whose domain was removed must stop being certifiable at once."""
        response = await client.get(
            "/api/v1/public/tls-check", params={"domain": "fcexample.localhost"}
        )
        assert response.headers["cache-control"] == "no-store"
