"""Supporters who asked to hear from the club.

Separate from `person` on purpose. A person is somebody the club holds records
about — a player, a parent, a coach — and creating one for every email address
typed into a footer form would put thousands of rows into the same table the
academy runs on, with none of the consent story that a marketing list needs.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantScoped, Timestamped, UUIDPrimaryKey


class NewsletterSubscriber(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    __tablename__ = "newsletter_subscriber"
    __table_args__ = (
        UniqueConstraint("tenant_id", "club_id", "email", name="uq_subscriber_email"),
        Index("ix_subscriber_club", "tenant_id", "club_id"),
    )

    club_id: Mapped[object] = mapped_column(PgUUID(as_uuid=True))
    email: Mapped[str] = mapped_column(CITEXT)
    locale: Mapped[str | None] = mapped_column(String(10))

    # When they agreed, and to what. A marketing list without this is one a
    # regulator can make the club delete in full.
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(32), default="SITE_FOOTER")
    unsubscribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
