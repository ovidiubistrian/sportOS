"""tenant visibility policy

Replaces the tenant table's policy so session bootstrap works under RLS.

`GET /me` must list the tenants a user may act in, which happens before any
tenant is selected. Under the previous policy (`id = current_tenant`) that
query returned nothing and login was impossible.

The fix keeps `tenant` under RLS and widens the policy to also admit tenants
the authenticated user holds a live role in — rather than resolving
memberships through a BYPASSRLS connection, which would have put a
cross-tenant-capable session on the login path of every request.

Revision ID: 8d4e0b17c992
Revises: 2c1f9a4d7b30
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.rls import enable, tenant_visibility_policy

revision: str = "8d4e0b17c992"
down_revision: str | None = "2c1f9a4d7b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for statement in tenant_visibility_policy():
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON tenant")
    # enable() is idempotent for the policy alone; re-create the narrow version.
    for statement in enable("tenant", column="id"):
        if statement.strip().upper().startswith("CREATE POLICY"):
            op.execute(statement)
