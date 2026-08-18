"""derive club timezone from country

Revision ID: 2c20579e61d9
Revises: c50270051936
Created: 2026-08-18 12:02:04.062151+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2c20579e61d9"
down_revision: str | None = "c50270051936"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

from app.core.countries import COUNTRIES
from app.core.rls import lift_force, restore_force


def upgrade() -> None:
    """Give every club and tenant the zone its country actually keeps.

    Only rows still sitting on `UTC` are touched, and `UTC` was the hardcoded
    default rather than anything a club chose — no country in the catalogue
    genuinely keeps it, so a row holding it is a row nobody set. A club that
    has deliberately picked a zone keeps it.

    This is a data migration with a real user-visible consequence: kick-off is
    stored in UTC and rendered in the club's zone, so a Romanian club left on
    `UTC` displayed every fixture three hours early through the summer. That is
    how it was found — not by a test.

    **Why the FORCE is lifted first, and why every data migration on a
    tenant-scoped table must do the same.** These tables carry
    `FORCE ROW LEVEL SECURITY`, which applies the tenant policy to the table
    owner as well — deliberately, so nothing bypasses isolation by accident.
    Migrations run as that owner with no `app.tenant_id` set, so the policy
    evaluates against NULL, matches nothing, and the UPDATE reports success
    having changed not one row. It fails closed *and silently*, which is the
    worst combination for a migration.

    Lifting FORCE lets the owner through without dropping the policy, so other
    connections stay isolated throughout. DDL is transactional in PostgreSQL:
    if anything below raises, the FORCE comes back with the rollback.
    """
    tables = ("club", "tenant")

    for statement in lift_force(list(tables)):
        op.execute(statement)

    try:
        for country in COUNTRIES:
            for table in tables:
                op.execute(
                    sa.text(
                        f"UPDATE {table} SET timezone = :tz "
                        "WHERE country_code = :code AND timezone = 'UTC'"
                    ).bindparams(tz=country.timezone, code=country.code)
                )
    finally:
        for statement in restore_force(list(tables)):
            op.execute(statement)


def downgrade() -> None:
    """Deliberately does nothing.

    Putting these rows back to `UTC` would restore a bug, and the column's own
    default already is `UTC` — so a genuine rollback of the code that reads it
    loses nothing by leaving correct data in place.
    """
