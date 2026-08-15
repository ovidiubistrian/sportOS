"""What happened on the club's website.

One table, because the questions a club asks are all the same question with a
different filter: how many people came, where from, what did they read, and how
many of them went on to do something. Splitting pageviews from conversions
would mean joining them back together for every funnel.

**No cookies and no personal data.** A visitor is a daily-rotating hash of
their address and browser — enough to count the same person twice on Tuesday,
useless for recognising them on Wednesday, and impossible to reverse into an IP
because the salt is thrown away. That is a deliberate product decision, not
only a legal one: a club site that needs a consent banner to count its own
readers is a worse product, and the banner is what destroys the numbers anyway.

Rows are raw. At club scale — thousands of views a month, not millions — the
aggregates run fast enough from the source, and keeping the raw rows means a
question nobody thought of in advance is still answerable next season.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantScoped, Timestamped, UUIDPrimaryKey

# What a visitor did. `PAGEVIEW` is most of it; the rest are the steps a club
# actually cares about, which is what makes a funnel answerable without
# instrumenting every button.
EVENT_KINDS = (
    "PAGEVIEW",
    "SHOP_VIEW",
    "BASKET_ADD",
    "CHECKOUT",
    "ORDER",
    "NEWSLETTER_SIGNUP",
    "ACCOUNT_SIGNUP",
    "TICKET_CLICK",
)

DEVICES = ("mobile", "desktop", "tablet", "other")


class AnalyticsEvent(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    __tablename__ = "analytics_event"
    __table_args__ = (
        CheckConstraint("kind IN " + str(EVENT_KINDS), name="analytics_kind_valid"),
        CheckConstraint("device IN " + str(DEVICES), name="analytics_device_valid"),
        # Every dashboard query starts with "this club, this window", so this is
        # the index that decides whether the page loads in 30ms or 3 seconds.
        Index("ix_analytics_club_time", "tenant_id", "club_id", "occurred_at"),
        Index("ix_analytics_club_kind_time", "tenant_id", "club_id", "kind", "occurred_at"),
        Index("ix_analytics_session", "tenant_id", "session_id"),
    )

    club_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(String(24), default="PAGEVIEW")

    # Both derived, neither reversible. The visitor hash rotates daily; the
    # session is minted server-side and expires after half an hour of silence.
    visitor_hash: Mapped[str] = mapped_column(String(64))
    session_id: Mapped[str] = mapped_column(String(36))

    path: Mapped[str] = mapped_column(String(300), default="/")
    # The host only, never the full referring URL: the path a stranger came
    # from can carry their search terms, and the club does not need them.
    referrer_host: Mapped[str | None] = mapped_column(String(160))

    utm_source: Mapped[str | None] = mapped_column(String(80))
    utm_medium: Mapped[str | None] = mapped_column(String(80))
    utm_campaign: Mapped[str | None] = mapped_column(String(120))

    # Where the visit came from, resolved from the address and then the address
    # is thrown away. Country is the useful one for a club; city is what makes
    # "most of our readers are in Reșița, but 200 are in Timișoara" answerable.
    country: Mapped[str | None] = mapped_column(String(2))
    city: Mapped[str | None] = mapped_column(String(80))

    device: Mapped[str] = mapped_column(String(10), default="other")
    browser: Mapped[str] = mapped_column(String(24), default="Other")
    locale: Mapped[str | None] = mapped_column(String(10))

    # Money, for the events that carry it — an order is worth more to a club
    # than a pageview, and a campaign that produced three orders should be
    # able to say what they were worth.
    value_minor: Mapped[int | None] = mapped_column(Integer)
