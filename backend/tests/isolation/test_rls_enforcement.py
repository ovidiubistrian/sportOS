"""RLS actually bites on a runtime connection.

`test_rls_sweep` proves the policies exist. This proves they work — through the
same role and the same `set_config` mechanism the application uses, because a
policy that exists but is bypassed by the runtime role protects nothing.
"""

from __future__ import annotations

import pytest
from sqlalchemy import NullPool, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import settings

pytestmark = pytest.mark.isolation


@pytest.fixture
async def runtime_engine() -> AsyncEngine:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    yield engine
    await engine.dispose()


async def _tenant_ids(admin_engine: AsyncEngine) -> tuple[str, str]:
    async with admin_engine.connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT id FROM tenant WHERE is_demo ORDER BY slug LIMIT 2")
            )
        ).all()
    assert len(rows) == 2, "Two demo tenants are required; run the demo seed."
    return str(rows[0][0]), str(rows[1][0])


async def _count_players(engine: AsyncEngine, tenant_id: str | None) -> int:
    async with engine.connect() as conn:
        await conn.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": tenant_id or ""},
        )
        return int(await conn.scalar(text("SELECT count(*) FROM player")) or 0)


async def test_missing_tenant_context_returns_no_rows(
    runtime_engine: AsyncEngine, admin_engine: AsyncEngine
) -> None:
    """The failure mode of a forgotten tenant context is emptiness, not a leak."""
    assert await _count_players(runtime_engine, None) == 0

    async with admin_engine.connect() as conn:
        total = int(await conn.scalar(text("SELECT count(*) FROM player")) or 0)
    assert total > 0, "Seed data missing — the assertion above would be vacuous."


async def test_each_tenant_sees_only_its_own_rows(
    runtime_engine: AsyncEngine, admin_engine: AsyncEngine
) -> None:
    """Every row belongs to exactly one tenant, and to no other.

    Asserted over *all* tenants rather than a fixed two: the counts have to
    partition the table however many there are, and hard-coding the number
    turns "someone signed a new club up" into a failing isolation test — which
    trains people to ignore the one suite that must never be ignored.
    """
    async with admin_engine.connect() as conn:
        tenant_ids = [
            str(row[0]) for row in (await conn.execute(text("SELECT id FROM tenant"))).all()
        ]
        total = int(await conn.scalar(text("SELECT count(*) FROM player")) or 0)

    assert len(tenant_ids) >= 2, "needs at least two tenants to mean anything"

    per_tenant = {
        tenant_id: await _count_players(runtime_engine, tenant_id) for tenant_id in tenant_ids
    }
    visible = sum(per_tenant.values())

    assert sum(1 for count in per_tenant.values() if count > 0) >= 2, (
        f"only one tenant has players, so the partition is vacuous: {per_tenant}"
    )
    assert visible == total, (
        "Tenant row counts do not partition the table — rows are visible to "
        f"more than one tenant, or to none. Seen {visible} across "
        f"{len(tenant_ids)} tenants against {total} rows."
    )


async def test_cross_tenant_insert_is_rejected_by_the_database(
    runtime_engine: AsyncEngine, admin_engine: AsyncEngine
) -> None:
    """The WITH CHECK clause stops a mislabelled write even if the app allows it."""
    first, second = await _tenant_ids(admin_engine)

    async with admin_engine.connect() as conn:
        club_id = await conn.scalar(
            text("SELECT id FROM club WHERE tenant_id = :t LIMIT 1"), {"t": first}
        )

    async with runtime_engine.connect() as conn:
        await conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": second})
        with pytest.raises(DBAPIError, match="row-level security"):
            await conn.execute(
                text(
                    """
                    INSERT INTO team
                        (id, tenant_id, club_id, name, code, gender, level,
                         is_academy, status, created_at, updated_at)
                    VALUES
                        (gen_random_uuid(), :other_tenant, :club, 'Injected', 'INJ',
                         'MALE', 'YOUTH', true, 'ACTIVE', now(), now())
                    """
                ),
                {"other_tenant": first, "club": club_id},
            )


async def test_tenant_table_shows_only_the_active_tenant(
    runtime_engine: AsyncEngine, admin_engine: AsyncEngine
) -> None:
    first, _ = await _tenant_ids(admin_engine)
    async with runtime_engine.connect() as conn:
        await conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": first})
        await conn.execute(text("SELECT set_config('app.user_id', '', true)"))
        rows = (await conn.execute(text("SELECT id FROM tenant"))).all()
    assert [str(r[0]) for r in rows] == [first]
