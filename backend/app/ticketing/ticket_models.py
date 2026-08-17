"""What a supporter holds: entitlements, tickets and credentials.

Three tables where one might look sufficient, and each answers a different
question:

- `EventEntitlement` — *may this person come in, to this seat, at this match?*
  The access-side record. It is what the scanner's manifest is built from.
- `Ticket` — *what was bought, for how much, by whom?* The commercial record.
  Finance reads this; it must stay stable and auditable for years.
- `AccessCredential` — *does this QR open this turnstile?* The technical record.
  Disposable by design: many over a ticket's life, exactly one ACTIVE.

The last split is ADR-0006 and predates this module. The reason is that access
technology turns over — static QR, rotating QR, wallet passes, NFC — while
ownership must not, and that a ticket handed to a friend is the same purchase
but must be a *different* QR with the old one dead the same second.

**The season-pass rule.** A season pass is not one ticket that works twenty
times. It mints a separate `EventEntitlement` for every included match, on the
same physical seat. That is what lets a holder release a single match back to
the club, transfer one game to a colleague, or have one match cancelled —
without any of it touching the other nineteen. Modelling it as one unlimited
credential would make every one of those operations impossible without
inventing a per-match exception table later.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantScoped, Timestamped, UUIDPrimaryKey

SEASON_PRODUCT_STATUSES = ("DRAFT", "ON_SALE", "CLOSED")

# Who may buy. RENEWAL_ONLY is the window in which last season's holders keep
# first claim on their own seat before it goes to the public.
SEASON_ELIGIBILITY = ("PUBLIC", "MEMBERS", "RENEWAL_ONLY")

SEASON_PASS_STATUSES = ("PENDING", "ACTIVE", "CANCELLED", "EXPIRED")

# Where the right to attend came from.
ENTITLEMENT_SOURCES = ("SINGLE", "SEASON_PASS", "COMPLIMENTARY")

# An entitlement's life. RELEASED is the season-pass holder handing one match
# back to the club; the seat returns to sale and the pass survives.
ENTITLEMENT_STATUSES = ("ACTIVE", "RELEASED", "TRANSFERRED", "CANCELLED", "REFUNDED")

TICKET_STATUSES = ("ISSUED", "VOID", "REFUNDED")

CREDENTIAL_STATUSES = ("ACTIVE", "REVOKED", "SUPERSEDED")


class SeasonTicketProduct(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """A season ticket a club offers, before anybody has bought one."""

    __tablename__ = "season_ticket_product"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "configuration_id"],
            ["venue_configuration.tenant_id", "venue_configuration.id"],
            name="fk_season_product_configuration",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_season_product_tenant_id_id"),
        CheckConstraint(
            "status IN " + str(SEASON_PRODUCT_STATUSES), name="season_product_status_valid"
        ),
        CheckConstraint(
            "eligibility IN " + str(SEASON_ELIGIBILITY), name="season_product_eligibility_valid"
        ),
        CheckConstraint("price_minor >= 0", name="season_product_price_non_negative"),
    )

    club_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    configuration_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    season_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)

    price_minor: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="RON")

    status: Mapped[str] = mapped_column(String(12), default="DRAFT")
    eligibility: Mapped[str] = mapped_column(String(16), default="PUBLIC")

    sales_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sales_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Until when last season's holder keeps their seat. Modelled now because
    # "renew and keep my seat" is the first thing a club asks for in year two,
    # and retrofitting a date onto sold passes is worse than carrying a null.
    renewal_deadline: Mapped[date | None] = mapped_column(Date)

    is_transferable: Mapped[bool] = mapped_column(default=True)


class SeasonTicketEvent(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """Which matches a season product includes.

    An explicit join rather than "every home match of the season", because the
    two differ: a cup run adds fixtures after the passes are sold, and a club
    decides case by case whether they are included.
    """

    __tablename__ = "season_ticket_event"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["season_ticket_product.tenant_id", "season_ticket_product.id"],
            name="fk_season_ticket_event_product",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["ticketed_event.tenant_id", "ticketed_event.id"],
            name="fk_season_ticket_event_event",
            ondelete="CASCADE",
        ),
        UniqueConstraint("product_id", "event_id", name="uq_season_ticket_event"),
    )

    product_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    event_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))


class SeasonPass(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """One sold season ticket, tied to one physical seat.

    The seat is stored as the master `seat_id` rather than as a per-event
    inventory row, because the pass's promise is about the *seat* — "the same
    seat all season" — and the per-match rows are derived from it.
    """

    __tablename__ = "season_pass"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["season_ticket_product.tenant_id", "season_ticket_product.id"],
            name="fk_season_pass_product",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_season_pass_tenant_id_id"),
        UniqueConstraint("tenant_id", "reference", name="uq_season_pass_reference"),
        # One live pass per seat per product. Partial, so that a cancelled
        # pass's seat can be sold to somebody else without deleting history.
        Index(
            "uq_season_pass_seat_live",
            "product_id",
            "seat_id",
            unique=True,
            postgresql_where=text("status IN ('PENDING', 'ACTIVE')"),
        ),
        CheckConstraint(
            "status IN " + str(SEASON_PASS_STATUSES), name="season_pass_status_valid"
        ),
    )

    product_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    seat_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))

    # Short and human — what the holder quotes on the phone.
    reference: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(12), default="PENDING")

    holder_name: Mapped[str] = mapped_column(String(160))
    holder_email: Mapped[str | None] = mapped_column(String(320))
    supporter_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    order_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    price_paid_minor: Mapped[int] = mapped_column(Integer, default=0)

    # Seat labels snapshotted, for the same reason as everywhere else: the
    # printed pass must keep reading correctly after a renumbering.
    stand_name: Mapped[str | None] = mapped_column(String(120))
    section_name: Mapped[str | None] = mapped_column(String(120))
    row_label: Mapped[str | None] = mapped_column(String(12))
    seat_label: Mapped[str | None] = mapped_column(String(12))


class EventEntitlement(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """The right to attend one event, in one place.

    Exactly one per occupied inventory row — that is the `uq_entitlement_seat`
    constraint, and it is the second line of defence against a seat being given
    to two people: even if the inventory state machine were wrong, a second
    entitlement for the same admission cannot be inserted.
    """

    __tablename__ = "event_entitlement"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["ticketed_event.tenant_id", "ticketed_event.id"],
            name="fk_entitlement_event",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "inventory_id"],
            ["event_seat_inventory.tenant_id", "event_seat_inventory.id"],
            name="fk_entitlement_inventory",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_entitlement_tenant_id_id"),
        UniqueConstraint("inventory_id", name="uq_entitlement_seat"),
        CheckConstraint(
            "source IN " + str(ENTITLEMENT_SOURCES), name="entitlement_source_valid"
        ),
        CheckConstraint(
            "status IN " + str(ENTITLEMENT_STATUSES), name="entitlement_status_valid"
        ),
        # A season-pass entitlement must name its pass, and a single sale must
        # not. Without this, releasing one match of a pass has nothing to find.
        CheckConstraint(
            "(source = 'SEASON_PASS') = (season_pass_id IS NOT NULL)",
            name="entitlement_season_pass_matches_source",
        ),
        Index("ix_entitlement_event_status", "tenant_id", "event_id", "status"),
        Index("ix_entitlement_pass", "tenant_id", "season_pass_id"),
    )

    event_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    inventory_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))

    source: Mapped[str] = mapped_column(String(16), default="SINGLE")
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")

    season_pass_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    order_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    order_line_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    ticket_type_code: Mapped[str] = mapped_column(String(24), default="ADULT")

    holder_name: Mapped[str | None] = mapped_column(String(160))
    supporter_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Ticket(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """The commercial record of one admission.

    Prices are snapshotted, like every other money field in this codebase: what
    somebody was charged must survive the price list being rewritten.
    """

    __tablename__ = "ticket"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "entitlement_id"],
            ["event_entitlement.tenant_id", "event_entitlement.id"],
            name="fk_ticket_entitlement",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_ticket_tenant_id_id"),
        UniqueConstraint("tenant_id", "ticket_number", name="uq_ticket_number"),
        UniqueConstraint("entitlement_id", name="uq_ticket_entitlement"),
        CheckConstraint("status IN " + str(TICKET_STATUSES), name="ticket_status_valid"),
        CheckConstraint("price_minor >= 0", name="ticket_price_non_negative"),
        Index("ix_ticket_event", "tenant_id", "event_id", "status"),
        Index("ix_ticket_order", "tenant_id", "order_id"),
    )

    event_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    entitlement_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))

    # Human-readable and quotable at the box office. Unique per tenant.
    ticket_number: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(12), default="ISSUED")

    ticket_type_code: Mapped[str] = mapped_column(String(24), default="ADULT")
    ticket_type_name: Mapped[str] = mapped_column(String(80), default="Adult")

    currency: Mapped[str] = mapped_column(String(3), default="RON")
    price_minor: Mapped[int] = mapped_column(Integer, default=0)
    vat_minor: Mapped[int] = mapped_column(Integer, default=0)
    fee_minor: Mapped[int] = mapped_column(Integer, default=0)

    order_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    season_pass_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    holder_name: Mapped[str | None] = mapped_column(String(160))
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AccessCredential(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """The QR itself: opaque, signed, and revocable without touching the sale.

    What the code carries is a random reference and a signature over
    `(ref, event_id, section, gate_mask, valid window, key_id)` — and nothing
    else. **No name, no email, no seat description, no order number.** A ticket
    photographed and posted online must reveal nothing about its holder; that
    is a privacy requirement, not a nicety, and it is why the seat labels live
    on the ticket rather than in the barcode.

    `key_id` names the signing key so keys can be rotated without invalidating
    everything already issued.
    """

    __tablename__ = "access_credential"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ticket_id"],
            ["ticket.tenant_id", "ticket.id"],
            name="fk_credential_ticket",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_credential_tenant_id_id"),
        # Globally unique, not merely per tenant: the scanner looks a code up
        # by reference, and a collision across tenants would be a supporter of
        # one club admitted to another's ground. 160 random bits make it
        # unlikely; the constraint makes it impossible.
        UniqueConstraint("reference", name="uq_credential_reference"),
        CheckConstraint(
            "status IN " + str(CREDENTIAL_STATUSES), name="credential_status_valid"
        ),
        # Exactly one live QR per ticket. A transfer revokes the old one and
        # inserts a new one; without this a race could leave two working codes
        # for the same seat.
        Index(
            "uq_credential_active_per_ticket",
            "ticket_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        Index("ix_credential_ticket", "tenant_id", "ticket_id"),
    )

    ticket_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    event_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))

    # The opaque payload printed as a QR. Unpredictable — derived from a CSPRNG,
    # never from the ticket number, which is sequential and guessable.
    reference: Mapped[str] = mapped_column(String(64))
    signature: Mapped[str] = mapped_column(String(120))
    key_id: Mapped[str] = mapped_column(String(32))

    status: Mapped[str] = mapped_column(String(12), default="ACTIVE")

    # Which gates this code opens, as a comma-separated list of gate codes.
    # Empty means every gate serving the seat's sector. Denormalised so the
    # offline manifest can be built without a join across the whole layout.
    gate_codes: Mapped[str | None] = mapped_column(String(240))

    # The sector this credential admits to. Stored because the signature covers
    # it: without it the server could mint a credential it could never verify
    # again, and the offline manifest would have nothing to match a gate on.
    section_code: Mapped[str] = mapped_column(String(24), default="")

    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The credential this one replaced, so a transfer chain is walkable.
    supersedes_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    version: Mapped[int] = mapped_column(SmallInteger, default=1)
