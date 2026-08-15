from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.cms.article_types import ARTICLE_TYPES
from app.core.models import Base, TenantScoped, Timestamped, UUIDPrimaryKey

CONTENT_KINDS = ("ARTICLE", "PAGE")
CONTENT_STATUSES = ("DRAFT", "IN_REVIEW", "SCHEDULED", "PUBLISHED", "ARCHIVED")
TRANSLATION_STATUSES = ("DRAFT", "READY")


class ContentCategory(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    __tablename__ = "content_category"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "club_id"],
            ["club.tenant_id", "club.id"],
            name="fk_content_category_club",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "club_id", "key", name="uq_content_category_key"),
        UniqueConstraint("tenant_id", "id", name="uq_content_category_tenant_id_id"),
    )

    club_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    key: Mapped[str] = mapped_column(String(48))
    name: Mapped[str] = mapped_column(String(120))
    position: Mapped[int] = mapped_column(SmallInteger, default=0)


class ContentItem(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """A piece of content, independent of language.

    The item carries lifecycle and scheduling; every word a reader sees lives in
    `content_translation`. Splitting them is what makes "published in Romanian,
    still being translated into German" representable — which it must be, since
    a tenant declares several supported locales and translations arrive late.
    """

    __tablename__ = "content_item"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "club_id"],
            ["club.tenant_id", "club.id"],
            name="fk_content_item_club",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["content_category.tenant_id", "content_category.id"],
            name="fk_content_item_category",
            ondelete="SET NULL",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_content_item_tenant_id_id"),
        CheckConstraint("kind IN " + str(CONTENT_KINDS), name="content_item_kind_valid"),
        CheckConstraint(
            "article_type IN " + str(ARTICLE_TYPES), name="content_item_article_type_valid"
        ),
        CheckConstraint("status IN " + str(CONTENT_STATUSES), name="content_item_status_valid"),
        # A scheduled item without a date would never publish; a published item
        # without a date could not be ordered. Both are unrepresentable.
        CheckConstraint(
            "(status <> 'SCHEDULED') OR (scheduled_for IS NOT NULL)",
            name="content_item_scheduled_needs_date",
        ),
        CheckConstraint(
            "(status <> 'PUBLISHED') OR (published_at IS NOT NULL)",
            name="content_item_published_needs_date",
        ),
        # The public list query.
        Index(
            "ix_content_published",
            "tenant_id",
            "club_id",
            "published_at",
            postgresql_where="status = 'PUBLISHED'",
        ),
        # The scheduler's only query, kept tiny by the partial predicate.
        Index(
            "ix_content_due",
            "scheduled_for",
            postgresql_where="status = 'SCHEDULED'",
        ),
        Index("ix_content_status", "tenant_id", "club_id", "status"),
        # The newsroom groups by type ("all departures", "match reports").
        Index("ix_content_article_type", "tenant_id", "club_id", "article_type"),
    )

    club_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    category_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    kind: Mapped[str] = mapped_column(String(16), default="ARTICLE")
    # Shapes the starter skeleton and the writing assistant's instructions.
    article_type: Mapped[str] = mapped_column(String(24), default="ANNOUNCEMENT")
    status: Mapped[str] = mapped_column(String(16), default="DRAFT")

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_pinned: Mapped[bool] = mapped_column(default=False)
    # The article's picture. On the item, not the translation: a photograph of a
    # signing is the same photograph in every language.
    cover_media_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    author_person_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    created_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    @property
    def is_public(self) -> bool:
        return self.status == "PUBLISHED"


class ContentTranslation(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """One language of one content item.

    `body` is a list of typed blocks, not HTML. Two reasons: the four site
    templates each render blocks in their own way, and structured content cannot
    carry a script tag — the templates render text nodes, so stored XSS is
    unrepresentable rather than merely sanitised.
    """

    __tablename__ = "content_translation"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "content_item_id"],
            ["content_item.tenant_id", "content_item.id"],
            name="fk_content_translation_item",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "content_item_id", "locale", name="uq_content_translation_item_locale"
        ),
        # Slugs are unique per club per language, so `/news/echipa-noastra` and
        # `/news/our-team` can coexist as the same article. club_id is
        # denormalised purely to make this index possible.
        UniqueConstraint("club_id", "locale", "slug", name="uq_content_translation_slug"),
        CheckConstraint(
            "status IN " + str(TRANSLATION_STATUSES),
            name="content_translation_status_valid",
        ),
        Index("ix_content_translation_lookup", "tenant_id", "club_id", "locale"),
    )

    content_item_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    club_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    locale: Mapped[str] = mapped_column(String(10))

    title: Mapped[str] = mapped_column(String(240))
    slug: Mapped[str] = mapped_column(String(240))
    excerpt: Mapped[str | None] = mapped_column(Text)
    body: Mapped[list] = mapped_column(JSONB, default=list)

    seo_title: Mapped[str | None] = mapped_column(String(240))
    seo_description: Mapped[str | None] = mapped_column(String(400))

    status: Mapped[str] = mapped_column(String(16), default="DRAFT")
    translated_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
