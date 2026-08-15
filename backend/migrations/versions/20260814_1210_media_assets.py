"""media assets

Revision ID: c4f92e1a7b60
Revises: 9b1f4c07ae52
Created: 2026-08-14 12:10:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.rls import disable, enable
from app.media.models import MEDIA_PURPOSES

revision: str = "c4f92e1a7b60"
down_revision: str | None = "9b1f4c07ae52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_asset",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("club_id", sa.UUID(), nullable=False),
        sa.Column("purpose", sa.String(length=24), nullable=False),
        sa.Column("visibility", sa.String(length=8), nullable=False),
        sa.Column("storage_key", sa.String(length=400), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("alt_text", sa.String(length=300), nullable=True),
        sa.Column("uploaded_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(f"purpose IN {MEDIA_PURPOSES}", name="media_purpose_valid"),
        sa.CheckConstraint(
            "visibility IN ('public', 'private')", name="media_visibility_valid"
        ),
        sa.CheckConstraint("width > 0 AND height > 0", name="media_dimensions_positive"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "club_id"],
            ["club.tenant_id", "club.id"],
            name="fk_media_asset_club",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_media_asset_tenant_id", "media_asset", ["tenant_id"])
    op.create_index("ix_media_club_purpose", "media_asset", ["tenant_id", "club_id", "purpose"])
    # Unique because the key is also the object's address in storage: two rows
    # claiming the same object would make deleting one break the other.
    op.create_index("uq_media_storage_key", "media_asset", ["storage_key"], unique=True)

    for statement in enable("media_asset"):
        op.execute(statement)


def downgrade() -> None:
    for statement in disable("media_asset"):
        op.execute(statement)
    op.drop_index("uq_media_storage_key", table_name="media_asset")
    op.drop_index("ix_media_club_purpose", table_name="media_asset")
    op.drop_index("ix_media_asset_tenant_id", table_name="media_asset")
    op.drop_table("media_asset")
