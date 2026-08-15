from __future__ import annotations

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantScoped, Timestamped, UUIDPrimaryKey

# What the image is *for*. Not a folder: the purpose decides where it may be
# rendered, what aspect ratio the admin crops to, and — for `PARTNER_LOGO` and
# `CREST` — that it is safe to serve unsigned.
MEDIA_PURPOSES = (
    "CREST",
    "HERO",
    "PARTNER_LOGO",
    "COMPETITION_BADGE",
    "ARTICLE_IMAGE",
    "TEAM_PHOTO",
    "PLAYER_PHOTO",
)


class MediaAsset(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """One uploaded image.

    The row is the record of truth; the object in storage is addressed by
    `storage_key`, which the application generates. The uploader's filename is
    kept as a label only — it is never part of a URL, because it is
    attacker-controlled and can itself be personal data.

    Dimensions are recorded at upload so the site can reserve layout space
    before the image loads, which is the difference between a page that settles
    and a page that jumps.
    """

    __tablename__ = "media_asset"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "club_id"],
            ["club.tenant_id", "club.id"],
            name="fk_media_asset_club",
            ondelete="CASCADE",
        ),
        CheckConstraint("purpose IN " + str(MEDIA_PURPOSES), name="media_purpose_valid"),
        CheckConstraint("visibility IN ('public', 'private')", name="media_visibility_valid"),
        CheckConstraint("width > 0 AND height > 0", name="media_dimensions_positive"),
        Index("uq_media_storage_key", "storage_key", unique=True),
        Index("ix_media_club_purpose", "tenant_id", "club_id", "purpose"),
    )

    club_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    purpose: Mapped[str] = mapped_column(String(24))
    visibility: Mapped[str] = mapped_column(String(8), default="public")

    storage_key: Mapped[str] = mapped_column(String(400))
    content_type: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)

    # Shown in the media library so an editor recognises their own upload.
    # Never used to build a URL.
    original_filename: Mapped[str | None] = mapped_column(String(255))
    # Required for anything that appears on the public site. An image with no
    # alt text is invisible to a screen reader and to search.
    alt_text: Mapped[str | None] = mapped_column(String(300))

    uploaded_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
