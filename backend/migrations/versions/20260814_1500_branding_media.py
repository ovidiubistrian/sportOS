"""crest and hero images on club branding

Revision ID: e71b3d5a9042
Revises: c4f92e1a7b60
Created: 2026-08-14 15:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e71b3d5a9042"
down_revision: str | None = "c4f92e1a7b60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("club_branding", sa.Column("crest_media_id", sa.UUID(), nullable=True))
    op.add_column("club_branding", sa.Column("hero_media_id", sa.UUID(), nullable=True))
    # SET NULL rather than RESTRICT: deleting an image a club has stopped using
    # should not fail because its home page still references it. The page loses
    # a crest; it does not lose the ability to delete.
    op.create_foreign_key(
        "fk_branding_crest",
        "club_branding",
        "media_asset",
        ["crest_media_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_branding_hero",
        "club_branding",
        "media_asset",
        ["hero_media_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_branding_hero", "club_branding", type_="foreignkey")
    op.drop_constraint("fk_branding_crest", "club_branding", type_="foreignkey")
    op.drop_column("club_branding", "hero_media_id")
    op.drop_column("club_branding", "crest_media_id")
