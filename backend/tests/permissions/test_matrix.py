"""Route-by-role permission matrix.

Every route is listed with the roles that may reach it. A route with no entry
fails the test — so permissions cannot be forgotten when an endpoint is added
under time pressure, which is exactly when they are forgotten.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from tests.routes import api_routes

pytestmark = pytest.mark.permissions

# route -> {user fixture name: expected status}
#   owner        TENANT_OWNER in FC Example
#   academy      ACADEMY_DIRECTOR, club-scoped
#   coach        COACH, scoped to U15 only
#   other_owner  TENANT_OWNER in a different tenant
MATRIX: dict[tuple[str, str], dict[str, int]] = {
    ("GET", "/api/v1/payments/settings"): {
        # The card gateway is the tenant's, not a club's: whoever holds these
        # credentials can take a supporter's money somewhere else. The academy
        # director runs an academy, which is not that.
        "owner": 200,
        "academy": 403,
        "coach": 403,
    },
    ("GET", "/api/v1/payments/calls"): {
        # The record of what was said to a bank. Same reasoning, and it carries
        # buyers' details besides.
        "owner": 200,
        "academy": 403,
        "coach": 403,
    },
    ("GET", "/api/v1/me"): {
        "owner": 200,
        "academy": 200,
        "coach": 200,
        "other_owner": 200,
    },
    ("GET", "/api/v1/players"): {
        "owner": 200,
        "academy": 200,
        "coach": 200,
        "other_owner": 200,
    },
    ("GET", "/api/v1/teams/{team_id}/staff"): {
        # `staff.profile.read` is on the club-wide roles, not on COACH — a
        # coach coaches, and the club's staff list is not part of that. They
        # still see the touchline on the public site like everybody else.
        "owner": 200,
        "academy": 200,
        "coach": 403,
    },
    ("GET", "/api/v1/staff"): {
        # Reading who works here needs authz.role.read: the academy director
        # has it, a team coach does not.
        "owner": 200,
        "academy": 200,
        "coach": 403,
    },
    ("GET", "/api/v1/staff/roles"): {
        "owner": 200,
        "academy": 200,
        "coach": 403,
    },
    ("GET", "/api/v1/email-templates"): {
        # The club's letters, gated on reading its content — the same
        # permission that governs the news they are written alongside.
        "owner": 200,
        "academy": 200,
        "coach": 403,
    },
    ("GET", "/api/v1/campaigns"): {
        "owner": 200,
        "academy": 200,
        "coach": 403,
    },
    ("GET", "/api/v1/analytics/overview"): {
        # The club's own numbers, gated on reading the club. A coach can see
        # them; a different tenant sees its own, never ours — proved in
        # tests/analytics/.
        "owner": 200,
        "academy": 200,
        "coach": 200,
    },
    ("GET", "/api/v1/sports"): {
        # Reference data, like the locale registry: anybody who can read the
        # club can read what sports exist.
        "owner": 200,
        "academy": 200,
        "coach": 200,
    },
    ("GET", "/api/v1/teams"): {
        "owner": 200,
        "academy": 200,
        "coach": 200,
        "other_owner": 200,
    },
    ("GET", "/api/v1/seasons"): {
        "owner": 200,
        "academy": 200,
        "coach": 200,
        "other_owner": 200,
    },
    ("POST", "/api/v1/players"): {
        # A coach may record attendance and evaluations, not register players.
        "owner": 201,
        "academy": 201,
        "coach": 403,
    },
    ("GET", "/api/v1/clubs/{club_id}/branding"): {
        "owner": 200,
        "academy": 200,
        "coach": 200,
    },
    ("GET", "/api/v1/competitions"): {
        # Platform reference data: the same list for everyone who may see a
        # squad, because two clubs in Liga 2 must be choosing the same Liga 2.
        "owner": 200,
        "academy": 200,
        "coach": 200,
        "other_owner": 200,
    },
    ("GET", "/api/v1/directory/clubs"): {
        # The opponent directory is shared reference data, like the competition
        # list above it: anyone who may see a squad may see who it could play.
        "owner": 200,
        "academy": 200,
        "coach": 200,
        "other_owner": 200,
    },
    ("GET", "/api/v1/content"): {
        # An academy director reads the newsroom; a team coach has no business
        # in it at all.
        "owner": 200,
        "academy": 200,
        "coach": 403,
    },
    ("GET", "/api/v1/ai/assistant"): {
        # Reading the assistant's status is a newsroom read, not an AI action —
        # it is what tells the editor whether the feature is even available.
        "owner": 200,
        "academy": 200,
        "coach": 403,
    },
}

# Routes intentionally excluded from the matrix, with the reason.
EXEMPT = {
    # The card gateway. Saving credentials and checking them are sensitive —
    # they answer 401 STEP_UP_REQUIRED even to somebody who holds the
    # permission, which this matrix cannot express. Covered in
    # tests/payments/test_settings.py together with the 403s.
    ("PUT", "/api/v1/payments/settings/{provider}"),
    ("POST", "/api/v1/payments/settings/{provider}/test"),
    ("GET", "/api/v1/payments/calls/{call_id}"),
    ("GET", "/api/v1/players/{player_id}"),  # covered by the isolation probe
    ("PATCH", "/api/v1/players/{player_id}"),  # covered below, needs a fixture id
    # Squad editing needs a real team and a real registration, so both are
    # exercised as sequences in tests/teams/test_squad_editing.py — including
    # the coach's 403 and the cross-tenant 404 this matrix would assert.
    ("PATCH", "/api/v1/teams/{team_id}"),
    ("PUT", "/api/v1/players/{player_id}/registration"),
    ("DELETE", "/api/v1/players/{player_id}"),
    # Design settings: covered in tests/tenants/test_public_site.py, which
    # exercises read, write, the coach's 403 and the cross-tenant 404 together.
    ("PUT", "/api/v1/clubs/{club_id}/branding"),
    # The article's cover and pin. Needs a real article and a real image, so it
    # is covered in tests/cms/ alongside the rest of the editorial flow.
    ("PATCH", "/api/v1/content/{item_id}"),
    # Public routes are unauthenticated by design — they carry no token and are
    # scoped by Host, so a role matrix does not apply. Their access rules are
    # tested in tests/tenants/test_public_site.py.
    ("GET", "/api/v1/public/site"),
    ("GET", "/api/v1/public/teams"),
    ("GET", "/api/v1/public/teams/{team_id}/squad"),
    ("GET", "/api/v1/public/news"),
    ("GET", "/api/v1/public/plans"),
    ("GET", "/api/v1/public/matches"),
    ("GET", "/api/v1/public/table"),
    # Sign-up is the one write path with no caller to authorize. Its guards
    # are rate limits and validation rather than permissions, and they are
    # tested in tests/identity/test_registration.py.
    ("POST", "/api/v1/public/register"),
    ("GET", "/api/v1/public/register/slug"),
    ("GET", "/api/v1/public/register/languages"),
    ("GET", "/api/v1/public/news/{slug}"),
    # The editorial workflow needs an article to act on, so it is tested as a
    # sequence in tests/cms/test_content.py — create, translate, publish,
    # archive — including the coach's 403 and the cross-tenant 404.
    ("GET", "/api/v1/content/{item_id}"),
    ("POST", "/api/v1/content"),
    ("PUT", "/api/v1/content/{item_id}/translations/{locale}"),
    ("POST", "/api/v1/content/{item_id}/status"),
    ("DELETE", "/api/v1/content/{item_id}"),
    # Assistant actions cost money, so they are gated by an entitlement as well
    # as a permission. tests/ai/test_assistant.py covers both refusals, the
    # quota, and the fact-preservation guardrails against a stub provider.
    ("POST", "/api/v1/ai/polish"),
    ("POST", "/api/v1/ai/headlines"),
    ("POST", "/api/v1/ai/usage/{usage_id}/outcome"),
    ("GET", "/api/v1/ai/article-types/{key}/skeleton"),
    # Platform-scoped: none of the four tenant fixtures may reach these at all,
    # so a tenant-role matrix says nothing useful. Covered in
    # tests/ai/test_assistant.py::TestPlatformControl.
    ("GET", "/api/v1/platform/ai"),
    ("PUT", "/api/v1/platform/ai/tenants/{tenant_id}"),
    # Uploads need a real multipart body and a real image, so they are tested
    # as a sequence in tests/media/test_upload.py — including what happens when
    # the bytes are not the image the request claims.
    # Creating a squad needs a club id, so it is exercised in the demo build
    # and by the onboarding flow rather than by a status-code matrix.
    ("POST", "/api/v1/teams"),
    ("POST", "/api/v1/seasons"),
    # Fixtures need a club and an opponent, so they are exercised as a sequence
    # in tests/competitions/test_matches.py — including the check that a club
    # cannot rewrite a match it is not playing in.
    ("GET", "/api/v1/matches"),
    ("POST", "/api/v1/matches"),
    ("PATCH", "/api/v1/matches/{match_id}"),
    ("DELETE", "/api/v1/matches/{match_id}"),
    ("POST", "/api/v1/competitions/join"),
    ("GET", "/api/v1/competitions/{season_id}/table"),
    ("GET", "/api/v1/competitions/entries"),
    # Adding an opponent writes to shared reference data, so it is tested with
    # the fixtures it exists to serve rather than by status code alone.
    ("POST", "/api/v1/directory/clubs"),
    # The shop. Products need a club and orders need a basket that was actually
    # filled, so both are exercised as sequences in tests/commerce/test_shop.py
    # — including the coach's 403 and the cross-tenant 404 this matrix asserts.
    ("GET", "/api/v1/products"),
    ("POST", "/api/v1/products"),
    ("PATCH", "/api/v1/products/{product_id}"),
    ("DELETE", "/api/v1/products/{product_id}"),
    ("GET", "/api/v1/orders"),
    ("POST", "/api/v1/orders/{order_id}/status"),
    # Asked by the proxy before it will obtain a certificate for a hostname.
    # Unauthenticated by necessity — the proxy has no session — and it answers
    # only "is this a domain you know". Covered in tests/tenants/.
    ("GET", "/api/v1/public/tls-check"),
    # Unauthenticated and host-scoped, like the rest of /public.
    ("POST", "/api/v1/public/newsletter"),
    # The analytics beacon. Unauthenticated by necessity — it is called by every
    # visitor to every club site — and covered in tests/analytics/.
    ("POST", "/api/v1/public/analytics/collect"),
    # The supporter's own account. Authenticated, but by a different audience:
    # a supporter holds no role in the tenant, so the staff matrix does not
    # describe them. Covered in tests/fans/.
    ("GET", "/api/v1/public/account"),
    ("PUT", "/api/v1/public/account"),
    ("DELETE", "/api/v1/public/account"),
    ("GET", "/api/v1/public/account/orders"),
    ("GET", "/api/v1/public/history"),
    ("GET", "/api/v1/public/shop"),
    ("GET", "/api/v1/public/basket"),
    ("PUT", "/api/v1/public/basket/lines"),
    ("POST", "/api/v1/public/basket/checkout"),
    # The super-admin console. Every route needs a real tenant and most need a
    # platform role, so they are exercised in tests/platform/test_console.py —
    # including the tenant owner's 403 and the step-up on impersonation.
    ("GET", "/api/v1/platform/tenants"),
    ("PATCH", "/api/v1/platform/tenants/{tenant_id}"),
    ("GET", "/api/v1/platform/plans"),
    ("PUT", "/api/v1/platform/tenants/{tenant_id}/subscription"),
    ("POST", "/api/v1/platform/tenants/{tenant_id}/impersonate"),
    ("DELETE", "/api/v1/platform/tenants/{tenant_id}/impersonate"),
    ("GET", "/api/v1/platform/competitions"),
    ("POST", "/api/v1/platform/competitions"),
    ("PATCH", "/api/v1/platform/competitions/{competition_id}"),
    # The league feed. Linking needs a real season and syncing spends a shared
    # API allowance, so both are exercised in tests/integrations/.
    ("GET", "/api/v1/clubs/{club_id}/feed"),
    ("PUT", "/api/v1/clubs/{club_id}/feed"),
    ("GET", "/api/v1/feed/teams"),
    # Reading the provider's catalogue — divisions in a country, then the clubs
    # in one. Same permission as the rest of the feed and no tenant data in the
    # answer, but each call spends from a shared allowance, which is why they
    # are behind the same gate as linking rather than open to any signed-in user.
    ("GET", "/api/v1/feed/leagues"),
    ("GET", "/api/v1/feed/leagues/{league_id}/teams"),
    ("POST", "/api/v1/clubs/{club_id}/feed/sync"),
    ("POST", "/api/v1/clubs/{club_id}/feed/history"),
    # Bringing in the provider's squad. Writes players, so the same permission
    # as editing them, and exercised in tests/integrations/ where a provider
    # response can be faked.
    ("POST", "/api/v1/clubs/{club_id}/feed/squad"),
    ("GET", "/api/v1/platform/api-football"),
    ("GET", "/api/v1/platform/api-football/links"),
    ("POST", "/api/v1/platform/api-football/links"),
    ("DELETE", "/api/v1/platform/api-football/links/{competition_season_id}"),
    ("POST", "/api/v1/platform/api-football/links/{competition_season_id}/sync"),
    # Staffing. Inviting somebody creates a real login in the identity
    # provider, so these are exercised as a sequence in tests/authz/test_staff.py
    # — including the escalation guard, which is the rule that matters.
    # A team's touchline. Adding somebody needs a real team and either an
    # existing person or a name, so it is exercised in tests/teams/.
    ("POST", "/api/v1/teams/{team_id}/staff"),
    ("PATCH", "/api/v1/teams/{team_id}/staff/{staff_id}"),
    ("DELETE", "/api/v1/teams/{team_id}/staff/{staff_id}"),
    ("GET", "/api/v1/public/teams/{team_id}/staff"),
    ("POST", "/api/v1/staff"),
    ("PUT", "/api/v1/staff/{user_id}/role"),
    ("POST", "/api/v1/staff/{user_id}/invitation"),
    ("DELETE", "/api/v1/staff/{user_id}"),
    # Email marketing. Sending needs a template, an audience with consent and a
    # working relay, so the whole path is exercised as a sequence in
    # tests/marketing/ — including that an unsubscribe removes somebody from
    # the next send.
    ("POST", "/api/v1/email-templates"),
    ("PATCH", "/api/v1/email-templates/{template_id}"),
    ("GET", "/api/v1/email-templates/{template_id}/preview"),
    ("GET", "/api/v1/campaigns/audience"),
    ("POST", "/api/v1/campaigns"),
    ("POST", "/api/v1/campaigns/{campaign_id}/send"),
    ("POST", "/api/v1/campaigns/{campaign_id}/test"),
    ("GET", "/api/v1/campaigns/{campaign_id}/recipients"),
    # Held from an email, not a session: the signature is what makes it safe.
    ("GET", "/api/v1/public/unsubscribe"),
    ("POST", "/api/v1/public/unsubscribe"),
    ("GET", "/api/v1/media"),
    ("POST", "/api/v1/media"),
    ("PATCH", "/api/v1/media/{asset_id}"),
    ("DELETE", "/api/v1/media/{asset_id}"),
}


def _registered_routes() -> set[tuple[str, str]]:
    return set(api_routes())


def test_every_route_has_a_matrix_entry() -> None:
    covered = set(MATRIX) | EXEMPT
    missing = sorted(_registered_routes() - covered)
    assert not missing, (
        "These routes have no permission-matrix entry:\n  "
        + "\n  ".join(f"{m} {p}" for m, p in missing)
        + "\nAdd them to MATRIX, or to EXEMPT with a comment saying where "
        "they are covered instead."
    )


def test_matrix_has_no_stale_entries() -> None:
    stale = sorted(set(MATRIX) - _registered_routes())
    assert not stale, f"MATRIX references routes that no longer exist: {stale}"


@pytest.mark.parametrize(("method", "path"), sorted(MATRIX))
async def test_matrix(
    method: str,
    path: str,
    client: httpx.AsyncClient,
    as_user: Any,
    demo: dict[str, Any],
) -> None:
    # The matrix is keyed by the route template; the request needs real ids.
    url = path.replace("{club_id}", demo["club_id"]).replace(
        # The U15, because it is the one the coach fixture is scoped to — which
        # is what makes a team-scoped expectation in the matrix mean anything.
        "{team_id}",
        demo["u15_team_id"],
    )

    body = None
    if method == "POST" and path == "/api/v1/players":
        body = {
            "club_id": demo["club_id"],
            "first_name": "Matrix",
            "last_name": "Probe",
        }

    for user, expected in MATRIX[(method, path)].items():
        payload = dict(body) if body else None
        if payload:
            # Unique per user so repeated runs do not collide on any constraint.
            payload["last_name"] = f"Probe-{user}"
        response = await client.request(method, url, headers=as_user(user), json=payload)
        assert response.status_code == expected, (
            f"{method} {path} as {user}: expected {expected}, "
            f"got {response.status_code} ({response.text[:200]})"
        )


async def test_coach_cannot_update_a_player_in_another_team(
    client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
) -> None:
    response = await client.patch(
        f"/api/v1/players/{demo['u19_player']['id']}",
        headers=as_user("coach"),
        json={"status": "INACTIVE"},
    )
    assert response.status_code in (403, 404), (
        "A U15 coach must not be able to modify a U19 player."
    )


async def test_permissions_reported_to_the_client_match_the_role(
    client: httpx.AsyncClient, as_user: Any
) -> None:
    coach = (await client.get("/api/v1/me", headers=as_user("coach"))).json()
    owner = (await client.get("/api/v1/me", headers=as_user("owner"))).json()

    assert "players.player.read" in coach["permissions"]
    assert "players.player.create" not in coach["permissions"]
    assert "finance.report.read" not in coach["permissions"]
    assert "finance.report.read" in owner["permissions"]
    assert set(coach["permissions"]) < set(owner["permissions"])
