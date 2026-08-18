"""club directory link

Revision ID: b17b99727013
Revises: 6d962b1c1340
Created: 2026-08-14 20:25:02.549880+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "b17b99727013"
down_revision: str | None = "6d962b1c1340"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has(table: str, column: str) -> bool:
    return column in {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    op.add_column("club", sa.Column("directory_club_id", sa.UUID(), nullable=True))

    # `tenant.directory_club_id` is dropped only where it exists. Nothing in
    # this chain ever creates it: it came from a migration that was overwritten
    # by a filename collision before anyone but development had applied it. So
    # a database built from scratch has never seen the column, and an
    # unconditional DROP fails on every fresh install — including CI, and
    # including the first production deploy.
    #
    # Kept rather than deleted because the development databases that did apply
    # the lost migration still carry the column, and this is what removes it.
    if _has("tenant", "directory_club_id"):
        op.drop_column("tenant", "directory_club_id")


def downgrade() -> None:
    if not _has("tenant", "directory_club_id"):
        op.add_column(
            "tenant",
            sa.Column("directory_club_id", sa.UUID(), autoincrement=False, nullable=True),
        )
    op.drop_column("club", "directory_club_id")
