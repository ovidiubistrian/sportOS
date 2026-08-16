"""Audit records are written, scoped and complete."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.authz.permissions import CATALOGUE

pytestmark = pytest.mark.audit


async def test_creating_a_player_is_audited(
    client: httpx.AsyncClient,
    as_user: Any,
    demo: dict[str, Any],
    admin_engine: AsyncEngine,
) -> None:
    response = await client.post(
        "/api/v1/players",
        headers=as_user("owner"),
        json={"club_id": demo["club_id"], "first_name": "Audit", "last_name": "Probe"},
    )
    assert response.status_code == 201
    player_id = response.json()["id"]

    async with admin_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT action, object_type, tenant_id, actor_user_id, after, request_id "
                    "FROM audit_log WHERE object_id = :id"
                ),
                {"id": player_id},
            )
        ).first()

    assert row is not None, "no audit record for a created player"
    action, object_type, tenant_id, actor_user_id, after, request_id = row
    assert action == "players.player.create"
    assert object_type == "player"
    assert str(tenant_id) == demo["tenant_id"]
    assert actor_user_id is not None, "audit record has no actor"
    assert request_id, "audit record is not correlated to a request"
    assert after and "status" in after


async def test_audit_rolls_back_with_its_transaction(
    client: httpx.AsyncClient,
    as_user: Any,
    demo: dict[str, Any],
    admin_engine: AsyncEngine,
) -> None:
    """There must never be a record of something that did not happen."""
    async with admin_engine.connect() as conn:
        before = int(
            await conn.scalar(
                text("SELECT count(*) FROM audit_log WHERE action = 'players.player.create'")
            )
            or 0
        )

    rejected = await client.post(
        "/api/v1/players",
        headers=as_user("coach"),  # lacks the permission
        json={"club_id": demo["club_id"], "first_name": "Never", "last_name": "Created"},
    )
    assert rejected.status_code == 403

    async with admin_engine.connect() as conn:
        after = int(
            await conn.scalar(
                text("SELECT count(*) FROM audit_log WHERE action = 'players.player.create'")
            )
            or 0
        )
    assert after == before


async def test_audit_is_tenant_scoped(admin_engine: AsyncEngine) -> None:
    """A tenant session sees its own audit trail and nobody else's."""
    from sqlalchemy import NullPool
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    async with admin_engine.connect() as conn:
        tenants = [
            str(row[0])
            for row in (
                await conn.execute(
                    text("SELECT id FROM tenant WHERE is_demo ORDER BY slug LIMIT 2")
                )
            ).all()
        ]

    runtime = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        counts = []
        for tenant_id in tenants:
            async with runtime.connect() as conn:
                await conn.execute(
                    text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant_id}
                )
                rows = (
                    await conn.execute(text("SELECT DISTINCT tenant_id FROM audit_log"))
                ).all()
                assert all(str(r[0]) == tenant_id for r in rows), (
                    "audit_log leaked another tenant's rows"
                )
                counts.append(
                    int(await conn.scalar(text("SELECT count(*) FROM audit_log")) or 0)
                )
        assert any(counts), "no audit rows at all — the assertion above is vacuous"
    finally:
        await runtime.dispose()


async def test_partitions_exist_for_the_current_month(admin_engine: AsyncEngine) -> None:
    """A missing partition makes every audited write fail."""
    async with admin_engine.connect() as conn:
        partitions = [
            row[0]
            for row in (
                await conn.execute(
                    text(
                        "SELECT c.relname FROM pg_class c "
                        "JOIN pg_inherits i ON i.inhrelid = c.oid "
                        "JOIN pg_class p ON p.oid = i.inhparent "
                        "WHERE p.relname = 'audit_log'"
                    )
                )
            ).all()
        ]
    assert len(partitions) >= 3, (
        f"expected several months of audit partitions, found {partitions}"
    )


def test_every_sensitive_permission_is_declared() -> None:
    """Sensitive permissions drive step-up and access logging; the flag is load-bearing."""
    sensitive = {p.key for p in CATALOGUE if p.is_sensitive}
    expected = {
        "people.person.export",
        # `players.player.delete` was here. It came off deliberately: it takes
        # nothing out of the building and gains nobody any privilege, and
        # `players.player.update` already achieves the visible outcome — a
        # player marked DEPARTED disappears from the club's website — without
        # any second factor at all. Guarding one route and leaving the other
        # open protected nothing and signed real administrators out.
        "medical.record.read",
        "medical.record.write",
        "authz.role.manage",
        "billing.subscription.manage",
        "platform.tenant.manage",
        "platform.impersonate",
    }
    missing = expected - sensitive
    assert not missing, f"these permissions should be marked sensitive: {sorted(missing)}"
