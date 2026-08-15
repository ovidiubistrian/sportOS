"""Supporters: the people who buy from a club, as opposed to the people who run it.

One account across the whole platform, not one per club. `user_account` is
already global — a login is a login — and a parent with children at two
academies, or somebody who moves city and follows a second side, should not be
made to keep two passwords for one platform. What is per club is the
*relationship*: this row.

Deliberately not `person`. A person is somebody a club holds records about — a
player, a parent, a coach — governed by the academy's own data rules. A
supporter who bought a scarf is not that, and quietly filing them in the same
table would put a marketing list inside the safeguarding perimeter.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantScoped, Timestamped, UUIDPrimaryKey


class Supporter(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """One person's relationship with one club."""

    __tablename__ = "supporter"
    __table_args__ = (
        UniqueConstraint("tenant_id", "club_id", "user_id", name="uq_supporter_club_user"),
        Index("ix_supporter_user", "user_id"),
    )

    club_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user_account.id", ondelete="CASCADE")
    )

    display_name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str | None] = mapped_column(CITEXT)
    phone: Mapped[str | None] = mapped_column(String(32))
    locale: Mapped[str | None] = mapped_column(String(10))

    # Marketing consent, separate from having an account. Signing in to check
    # an order is not agreeing to be emailed, and treating it as such is how a
    # club ends up on a regulator's desk.
    marketing_opt_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
