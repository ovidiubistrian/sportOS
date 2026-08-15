"""The live database matches the model registry.

Compares what is actually in PostgreSQL against what the models declare, so a
table created by a migration without its RLS policy fails here rather than in
production. This is why the RLS migration can safely hardcode its table list.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core import model_registry  # noqa: F401
from app.core.models import Base, is_tenant_scoped
from tests.isolation.test_model_sweep import GLOBAL_MODELS

pytestmark = pytest.mark.isolation

# Tables that are not `TenantScoped` — because `tenant_id` is nullable, or
# because the row *is* the tenant — but still carry a tenant policy.
POLICY_ON_GLOBAL_TABLES = {
    "tenant",  # policy keyed on `id`
    "audit_log",  # NULL tenant_id = a platform action, invisible to tenants
    "entitlement",
    "tenant_subscription",
}


async def _rls_state(engine: AsyncEngine) -> dict[str, tuple[bool, bool, int]]:
    query = text(
        """
        SELECT c.relname,
               c.relrowsecurity,
               c.relforcerowsecurity,
               (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) AS policies
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind IN ('r', 'p')
          -- Partitions inherit the parent's policy and are never queried
          -- directly, so they are not separate subjects for this sweep.
          AND NOT c.relispartition
        """
    )
    async with engine.connect() as conn:
        rows = (await conn.execute(query)).all()
    return {r[0]: (r[1], r[2], r[3]) for r in rows}


def _expected_protected_tables() -> set[str]:
    return {
        m.class_.__tablename__ for m in Base.registry.mappers if is_tenant_scoped(m.class_)
    } | POLICY_ON_GLOBAL_TABLES


async def test_every_tenant_scoped_table_has_rls_enabled_and_forced(
    admin_engine: AsyncEngine,
) -> None:
    state = await _rls_state(admin_engine)
    problems: list[str] = []

    for table in sorted(_expected_protected_tables()):
        if table not in state:
            problems.append(f"{table}: table missing from the database")
            continue
        enabled, forced, policies = state[table]
        if not enabled:
            problems.append(f"{table}: RLS not enabled")
        if not forced:
            # Without FORCE, the owning role silently bypasses the policy.
            problems.append(f"{table}: RLS not FORCEd")
        if policies == 0:
            problems.append(f"{table}: no policy defined")

    assert not problems, (
        "Tables are missing row-level security. Add them to the RLS migration:\n  "
        + "\n  ".join(problems)
    )


async def test_no_unexpected_table_lacks_protection(admin_engine: AsyncEngine) -> None:
    """Catches a table created by a migration but never added to any model."""
    state = await _rls_state(admin_engine)
    known = {m.class_.__tablename__ for m in Base.registry.mappers} | {"alembic_version"}
    orphans = sorted(set(state) - known)
    assert not orphans, (
        f"Tables exist in the database with no corresponding model: {orphans}. "
        "Either add the model or drop the table."
    )


async def test_runtime_role_cannot_bypass_rls(admin_engine: AsyncEngine) -> None:
    """The application role must never hold BYPASSRLS.

    If it does, every other layer of the isolation defence is decorative.
    """
    async with admin_engine.connect() as conn:
        result = (
            await conn.execute(
                text("SELECT rolname, rolbypassrls FROM pg_roles WHERE rolname = 'app_runtime'")
            )
        ).first()
    assert result is not None, "app_runtime role does not exist"
    assert result[1] is False, "app_runtime must not have BYPASSRLS"


def test_global_allow_list_matches_unprotected_tables() -> None:
    protected = _expected_protected_tables()
    unprotected = {
        m.class_.__tablename__
        for m in Base.registry.mappers
        if m.class_.__tablename__ not in protected
    }
    assert unprotected <= GLOBAL_MODELS, (
        f"Tables without RLS that are not on the allow-list: "
        f"{sorted(unprotected - GLOBAL_MODELS)}"
    )
