"""Row Level Security statements used by migrations.

Migrations take an explicit list of table names rather than reading the live
metadata: a migration must mean the same thing forever, and metadata changes.
`tests/isolation/test_rls_sweep.py` compares the live database against the
model registry, so a table added without its RLS migration fails CI rather than
shipping unprotected.
"""

from __future__ import annotations

TENANT_SETTING = "app.tenant_id"

# NULL when unset, so the comparison is never true and the query returns
# nothing. A missing tenant context fails closed.
_TENANT_EXPR = f"nullif(current_setting('{TENANT_SETTING}', true), '')::uuid"


def enable(table: str, *, column: str = "tenant_id") -> list[str]:
    """Enable and force RLS, with a tenant-equality policy.

    FORCE is what makes this hold for the table owner too — without it the
    migrator role (and anything that ever runs as owner) silently bypasses the
    policy.
    """
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        f"""
        CREATE POLICY tenant_isolation ON {table}
            USING ({column} = {_TENANT_EXPR})
            WITH CHECK ({column} = {_TENANT_EXPR})
        """,
    ]


def disable(table: str) -> list[str]:
    return [
        f"DROP POLICY IF EXISTS tenant_isolation ON {table}",
        f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY",
    ]


USER_SETTING = "app.user_id"
_USER_EXPR = f"nullif(current_setting('{USER_SETTING}', true), '')::uuid"


def tenant_visibility_policy() -> list[str]:
    """The `tenant` table's own policy.

    Session bootstrap has to answer "which tenants may this user act in?"
    *before* a tenant is chosen, so a policy keyed only on the active tenant
    would make login impossible. Rather than bypass RLS for that query, the
    policy also admits tenants the authenticated user holds a live role in.

    `role_assignment` is intentionally not under RLS (see the migration notes),
    so this subquery is evaluated without recursion.
    """
    return [
        "DROP POLICY IF EXISTS tenant_isolation ON tenant",
        f"""
        CREATE POLICY tenant_isolation ON tenant
            USING (
                id = {_TENANT_EXPR}
                OR EXISTS (
                    SELECT 1 FROM role_assignment ra
                    WHERE ra.tenant_id = tenant.id
                      AND ra.user_id = {_USER_EXPR}
                      AND ra.revoked_at IS NULL
                )
            )
            WITH CHECK (id = {_TENANT_EXPR})
        """,
    ]


def enable_all(tables: list[str]) -> list[str]:
    return [stmt for table in tables for stmt in enable(table)]


def disable_all(tables: list[str]) -> list[str]:
    return [stmt for table in tables for stmt in disable(table)]
