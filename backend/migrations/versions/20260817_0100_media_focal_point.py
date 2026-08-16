"""media focal point

Revision ID: b1d7c40a9e52
Revises: 7e27681dce9b
Created: 2026-08-17 01:00:00.000000+00:00

One image is rendered into frames of very different shapes — a hero that is
nearly 3:1 on a desktop and nearly square on a phone, a feed card that is
taller than it is wide. `object-fit: cover` crops whatever does not fit, from
the centre, so the same photograph loses its sides on one screen and its sky on
another. A stadium shot that reads perfectly on a desktop came out as a hillside
on a phone.

The centre is only ever a guess. These two say where the picture actually is,
as a fraction of its own width and height, so every frame crops around the same
point. They default to the centre, which is what the code did before and is
right often enough that a club need never touch it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b1d7c40a9e52"
down_revision: str | None = "7e27681dce9b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Additive, with a server default, so the running deployment keeps working
    # against the new column between the migration and the new code.
    op.add_column(
        "media_asset",
        sa.Column("focal_x", sa.Float(), nullable=False, server_default="0.5"),
    )
    op.add_column(
        "media_asset",
        sa.Column("focal_y", sa.Float(), nullable=False, server_default="0.5"),
    )
    op.create_check_constraint(
        "media_focal_in_range",
        "media_asset",
        "focal_x >= 0 AND focal_x <= 1 AND focal_y >= 0 AND focal_y <= 1",
    )


def downgrade() -> None:
    op.drop_constraint("media_focal_in_range", "media_asset", type_="check")
    op.drop_column("media_asset", "focal_y")
    op.drop_column("media_asset", "focal_x")
