"""Shared test fixtures.

These tests run against the Docker Compose stack, not against mocks: real
PostgreSQL (so RLS, partial indexes and constraints are exercised) and real
Keycloak (so token verification is exercised). A suite that mocks the database
cannot prove tenant isolation, which is the thing most worth proving.

    docker compose up -d
    docker compose exec api pytest
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import settings

API_BASE = os.getenv("TEST_API_URL", "http://localhost:8000")
TOKEN_URL = (
    f"{os.getenv('OIDC_ISSUER', 'http://keycloak:8080/realms/football-os')}"
    "/protocol/openid-connect/token"
)

USERS = {
    "owner": "owner@fcexample.test",
    "academy": "academy@fcexample.test",
    "coach": "coach.u15@fcexample.test",
    "other_owner": "owner@northern.test",
    "platform": "platform@footbola.test",
}


def _fetch_token(username: str) -> str:
    response = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "password",
            "client_id": "admin-web",
            "username": username,
            "password": "password",
        },
        timeout=20.0,
    )
    response.raise_for_status()
    return str(response.json()["access_token"])


@pytest.fixture(scope="session")
def tokens() -> dict[str, str]:
    return {name: _fetch_token(email) for name, email in USERS.items()}


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(base_url=API_BASE, timeout=30.0) as http:
        yield http


@pytest.fixture
def as_user(tokens: dict[str, str]) -> Any:
    def _headers(name: str, tenant_id: str | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {tokens[name]}"}
        if tenant_id:
            headers["X-Tenant-Id"] = tenant_id
        return headers

    return _headers


@pytest.fixture(scope="session")
def demo(tokens: dict[str, str]) -> dict[str, Any]:
    """Ids from the demo seed, resolved once per session.

    Fetched through the API rather than the database so the fixture itself
    proves the happy path before any test asserts on the unhappy ones.
    """

    def get(user: str, path: str) -> Any:
        response = httpx.get(
            f"{API_BASE}{path}",
            headers={"Authorization": f"Bearer {tokens[user]}"},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()

    me = get("owner", "/api/v1/me")
    other_me = get("other_owner", "/api/v1/me")
    teams = {t["code"]: t for t in get("owner", "/api/v1/teams")}

    def first_player(user: str, query: str = "") -> dict[str, Any]:
        return get(user, f"/api/v1/players?limit=1{query}")["data"][0]

    return {
        "tenant_id": me["active_tenant"]["id"],
        "other_tenant_id": other_me["active_tenant"]["id"],
        "club_id": me["clubs"][0]["id"],
        "teams": teams,
        "u15_team_id": teams["U15"]["id"],
        "u19_team_id": teams["U19"]["id"],
        "u19_player": first_player("owner", f"&team_id={teams['U19']['id']}"),
        "u15_player": first_player("owner", f"&team_id={teams['U15']['id']}"),
        "other_tenant_player": first_player("other_owner"),
    }


@pytest.fixture(scope="session")
def sync_client(tokens: dict[str, str]) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=API_BASE, timeout=30.0) as http:
        yield http


@pytest.fixture
async def admin_engine() -> AsyncIterator[AsyncEngine]:
    """A short-lived engine for schema introspection.

    Not the module-level `platform_engine`: that one is created at import time
    and pools connections against whichever event loop was running then, while
    pytest-asyncio gives each test a fresh loop. Reusing it makes tests pass
    alone and fail in a suite — so introspection tests get their own engine
    with no pooling at all.
    """
    engine = create_async_engine(settings.database_platform_url, poolclass=NullPool, echo=False)
    try:
        yield engine
    finally:
        await engine.dispose()
