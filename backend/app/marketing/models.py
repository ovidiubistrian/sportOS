"""Email marketing: who may be written to, what is sent, and what happened.

Three tables and one rule. The rule is consent: nothing here can address a
person who has not asked to hear from the club, and every send carries a way
out. That is not decoration — a club's marketing list is the one thing in this
product a regulator will ask about first, and the answer has to be a timestamp,
not a habit.

The audience is deliberately *derived* rather than stored. A campaign records
which pool it was aimed at (newsletter subscribers, supporters who opted in, or
both) and resolves it at send time, so somebody who unsubscribes on Tuesday is
already gone from Wednesday's campaign without anybody remembering to prune a
list. A stored list is a list that goes stale silently.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantScoped, Timestamped, UUIDPrimaryKey

# Who a campaign is aimed at. Both pools carry their own consent record, and
# `EVERYONE` is the union of the two — never "every address we hold".
AUDIENCES = ("NEWSLETTER", "SUPPORTERS", "EVERYONE")

CAMPAIGN_STATUSES = ("DRAFT", "SCHEDULED", "SENDING", "SENT", "FAILED", "CANCELLED")

RECIPIENT_STATUSES = ("PENDING", "SENT", "FAILED", "BOUNCED", "UNSUBSCRIBED")

# What the club is writing about. Not a category for its own sake: it decides
# the default template and, later, which supporters consider it relevant.
CAMPAIGN_KINDS = ("NEWS", "OFFER", "MATCHDAY", "MEMBERSHIP", "ANNOUNCEMENT")


class EmailTemplate(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """A reusable letter, in the club's own colours.

    The body is the same typed block list the CMS uses, not stored HTML. A club
    editing a newsletter is doing what it already does when writing an article,
    and the renderer — not the author — decides what an email-safe table looks
    like. It also means there is no route by which a pasted `<script>` reaches
    somebody's inbox.
    """

    __tablename__ = "email_template"
    __table_args__ = (
        UniqueConstraint("tenant_id", "club_id", "key", name="uq_email_template_key"),
        # The composite a tenant-scoped foreign key needs: a campaign may only
        # reference a template inside its own tenant, which the database has to
        # be able to prove rather than trust the application about.
        UniqueConstraint("tenant_id", "id", name="uq_email_template_tenant_id_id"),
        Index("ix_email_template_club", "tenant_id", "club_id"),
    )

    club_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    key: Mapped[str] = mapped_column(String(48))
    name: Mapped[str] = mapped_column(String(120))
    locale: Mapped[str | None] = mapped_column(String(10))

    subject: Mapped[str] = mapped_column(String(200))
    # The line an inbox shows after the subject. Empty means the client picks
    # the first sentence of the body, which is rarely the sentence you wanted.
    preheader: Mapped[str | None] = mapped_column(String(200))
    blocks: Mapped[list] = mapped_column(JSONB, default=list)

    # A call to action, because most club emails have exactly one: buy the
    # shirt, renew the membership, get the ticket.
    cta_label: Mapped[str | None] = mapped_column(String(48))
    cta_url: Mapped[str | None] = mapped_column(String(500))

    is_active: Mapped[bool] = mapped_column(default=True)


class Campaign(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """One send, to one audience, from one template."""

    __tablename__ = "campaign"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "template_id"],
            ["email_template.tenant_id", "email_template.id"],
            name="fk_campaign_template",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_campaign_tenant_id_id"),
        CheckConstraint("status IN " + str(CAMPAIGN_STATUSES), name="campaign_status_valid"),
        CheckConstraint("audience IN " + str(AUDIENCES), name="campaign_audience_valid"),
        CheckConstraint("kind IN " + str(CAMPAIGN_KINDS), name="campaign_kind_valid"),
        Index("ix_campaign_club_status", "tenant_id", "club_id", "status"),
    )

    club_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    template_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))

    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(16), default="NEWS")
    audience: Mapped[str] = mapped_column(String(16), default="NEWSLETTER")
    # Narrow the pool to one language, for a club that publishes in two and
    # does not want to send Romanian to its Hungarian-speaking supporters.
    locale: Mapped[str | None] = mapped_column(String(10))

    status: Mapped[str] = mapped_column(String(16), default="DRAFT")
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Counters rather than a count(*) over recipients: a club watching a send
    # refreshes this every few seconds, and the recipient table is the biggest
    # one this module has.
    total: Mapped[int] = mapped_column(Integer, default=0)
    sent: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    opened: Mapped[int] = mapped_column(Integer, default=0)
    clicked: Mapped[int] = mapped_column(Integer, default=0)
    unsubscribed: Mapped[int] = mapped_column(Integer, default=0)

    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))


class CampaignRecipient(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """One address, one campaign, one outcome.

    Written before the send, not after, so a crash halfway through a thousand
    addresses is resumable and nobody is written to twice — the unique
    constraint is what makes "send" safe to retry.
    """

    __tablename__ = "campaign_recipient"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "campaign_id"],
            ["campaign.tenant_id", "campaign.id"],
            name="fk_recipient_campaign",
            ondelete="CASCADE",
        ),
        UniqueConstraint("campaign_id", "email", name="uq_recipient_once"),
        CheckConstraint("status IN " + str(RECIPIENT_STATUSES), name="recipient_status_valid"),
        Index("ix_recipient_campaign_status", "tenant_id", "campaign_id", "status"),
    )

    campaign_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    email: Mapped[str] = mapped_column(CITEXT)
    # Which pool this address came from, so a club can see that its offer
    # reached 300 newsletter readers and 40 account holders.
    source: Mapped[str] = mapped_column(String(16), default="NEWSLETTER")

    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    clicked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(300))
