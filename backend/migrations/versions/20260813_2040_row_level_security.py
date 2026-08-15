"""row level security

Layer 3 of the tenant isolation defence (docs/architecture/04-multitenancy.md).

The table list is written out explicitly rather than read from the model
registry: a migration must mean the same thing in five years, and metadata
changes. `tests/isolation/test_rls_sweep.py` compares the live database against
the registry, so a table added without its RLS migration fails CI.

Revision ID: 2c1f9a4d7b30
Revises: 75b1d44988b4
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.rls import disable_all, enable, enable_all

revision: str = "2c1f9a4d7b30"
down_revision: str | None = "75b1d44988b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_SCOPED_TABLES = [
    "club",
    "club_domain",
    "person",
    "person_role_flag",
    "season",
    "team",
    "player",
    "player_registration",
]

# Deliberately NOT under RLS, with the reason recorded:
#
#   tenant           has its own policy on `id` (below) — it *is* the tenant.
#   user_account     global identity; one login may exist in several tenants.
#   role,
#   role_permission  system templates have no tenant.
#   role_assignment  read during session bootstrap, before a tenant is known.
#                    Always filtered by the authenticated user_id.
#   permission       static reference data.


def upgrade() -> None:
    for statement in enable_all(TENANT_SCOPED_TABLES):
        op.execute(statement)

    # The tenant row itself: a request may only see the tenant it is scoped to.
    for statement in enable("tenant", column="id"):
        op.execute(statement)


def downgrade() -> None:
    for statement in disable_all([*TENANT_SCOPED_TABLES, "tenant"]):
        op.execute(statement)
