"""Cross-tenant and cross-scope access probes.

The probe list is derived from the application's own route table, so a new
detail endpoint is covered the day it is added rather than when someone
remembers to write a test for it.

Expectation everywhere: **404, not 403**. A 403 on another tenant's object
confirms that the object exists, which is itself a disclosure.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from tests.routes import detail_routes

pytestmark = pytest.mark.isolation


def test_probe_list_is_not_empty() -> None:
    """Guards against the probe silently covering nothing."""
    assert detail_routes(), "No detail routes discovered — the probe is vacuous."


async def test_other_tenants_object_is_not_found(
    client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
) -> None:
    foreign_id = demo["other_tenant_player"]["id"]

    probed = 0
    for _method, path in detail_routes():
        url = path.replace("{player_id}", foreign_id)
        if "{" in url:
            continue  # a route whose parameter we have no sample id for yet
        probed += 1
        response = await client.get(url, headers=as_user("owner"))
        assert response.status_code == 404, (
            f"{path} returned {response.status_code} for another tenant's id. "
            f"Anything other than 404 leaks existence."
        )
        assert response.json()["code"] == "NOT_FOUND"

    assert probed, "No detail route was actually probed."


async def test_own_tenants_object_is_found(
    client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
) -> None:
    """The negative tests above are only meaningful if the positive one passes."""
    response = await client.get(
        f"/api/v1/players/{demo['u19_player']['id']}", headers=as_user("owner")
    )
    assert response.status_code == 200
    assert response.json()["id"] == demo["u19_player"]["id"]


async def test_team_scoped_user_cannot_read_a_sibling_team(
    client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
) -> None:
    """The U15 coach may read their own players and no others."""
    own = await client.get(
        f"/api/v1/players/{demo['u15_player']['id']}", headers=as_user("coach")
    )
    assert own.status_code == 200

    sibling = await client.get(
        f"/api/v1/players/{demo['u19_player']['id']}", headers=as_user("coach")
    )
    assert sibling.status_code == 404, "A team-scoped coach reached a player in another team."


async def test_collections_are_narrowed_to_scope(
    client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
) -> None:
    """Permission to list is not permission to list everything."""

    async def total(user: str) -> int:
        response = await client.get(
            "/api/v1/players?limit=1&with_total=true", headers=as_user(user)
        )
        assert response.status_code == 200
        return int(response.json()["page"]["total"])

    owner_total = await total("owner")
    coach_total = await total("coach")
    other_total = await total("other_owner")

    assert coach_total < owner_total, (
        f"The U15 coach sees {coach_total} players and the owner {owner_total}; "
        "the scope filter is not narrowing the collection."
    )
    assert other_total not in (owner_total, 0)


async def test_tenant_header_for_a_foreign_tenant_is_rejected(
    client: httpx.AsyncClient, as_user: Any, demo: dict[str, Any]
) -> None:
    """A submitted tenant id is a request, never an authority."""
    response = await client.get(
        "/api/v1/me", headers=as_user("owner", tenant_id=demo["other_tenant_id"])
    )
    assert response.status_code == 400
    assert response.json()["code"] == "TENANT_CONTEXT_MISSING"


async def test_unauthenticated_requests_are_rejected(client: httpx.AsyncClient) -> None:
    for path in ("/api/v1/me", "/api/v1/players", "/api/v1/teams"):
        response = await client.get(path)
        assert response.status_code == 401, f"{path} is reachable without a token"


async def test_forged_token_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/api/v1/players", headers={"Authorization": "Bearer not.a.real.token"}
    )
    assert response.status_code == 401
