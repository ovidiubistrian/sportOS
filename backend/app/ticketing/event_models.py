"""Ticketed events: the frozen copy of a stadium, and what is for sale in it.

The rule this module exists to enforce, stated once:

    **The live venue configuration is never match inventory.**

When an event is created it takes an `EventConfigurationSnapshot` — the whole
layout serialised — and mints one `EventSeatInventory` row per admission. From
that moment the event owes the master configuration nothing. A club that
redraws a stand, deletes a sector or republishes the layout changes no
published match, no sold ticket, no reservation and no past report, because
none of them read the master any more.

That is why the inventory row carries the seat's labels rather than joining to
`seat` for them. It is denormalised on purpose: a ticket sold in August must
still print "North Stand, Row G, seat 12" after the row is renamed in January.

**Naming.** The specification calls this `MatchEvent`. That name is taken here:
in `app/competitions/models.py` a `MatchEvent` is a goal or a card. And `Match`
in that module is *global* reference data — one fixture shared by both clubs
and the league — whereas a ticketed event belongs to exactly one club, the one
selling. So this is `TicketedEvent`, and it points at the global match when
there is one.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantScoped, Timestamped, UUIDPrimaryKey

EVENT_STATUSES = ("DRAFT", "PUBLISHED", "CLOSED", "CANCELLED")

# The club's own pricing tier for a fixture. A derby is an A; a midweek cup tie
# against a fourth-tier side is a C. Drives which price list applies.
EVENT_CATEGORIES = ("A", "B", "C")

# Every state an admission can be in. The distinctions are operational, not
# cosmetic — a report has to be able to answer "how many seats are we holding
# back from sale, and why", and one `is_available` boolean cannot.
INVENTORY_STATES = (
    # Sellable right now.
    "AVAILABLE",
    # In somebody's basket. Expires — see `hold_expires_at`.
    "CART_HELD",
    # Paid for but not yet ticketed, or held by the box office for collection.
    "RESERVED",
    # Sold. A ticket exists.
    "SOLD",
    # Taken out of sale entirely: broken seat, camera platform, safety closure.
    # Reduces sellable capacity and is reported separately from unsold.
    "HARD_BLOCKED",
    # Set aside for somebody — sponsor, press, away club — and returnable to
    # public sale if unclaimed.
    "SOFT_ALLOCATED",
    # Issued at no charge. Distinct from SOLD so revenue reports stay honest.
    "COMPLIMENTARY",
    # Was sold, has been refunded, and is back on sale. Distinct from AVAILABLE
    # so that "never sold" and "sold and given back" remain separable.
    "REFUNDED_RELEASED",
)

# Which states occupy a seat, i.e. make it unsellable to somebody else. Used by
# the availability queries and by the capacity report.
UNSELLABLE_STATES = (
    "CART_HELD",
    "RESERVED",
    "SOLD",
    "HARD_BLOCKED",
    "SOFT_ALLOCATED",
    "COMPLIMENTARY",
)

# Where a price list applies. Resolution walks EVENT → SEASON → VENUE and takes
# the first rule it finds, so a club sets prices once and overrides per match.
PRICE_LIST_SCOPES = ("VENUE", "SEASON", "EVENT")

ALLOCATION_KINDS = ("HARD_HOLD", "SOFT_ALLOCATION")

# Why inventory is being held back. Recorded because "why is the away end
# closed" is a question somebody asks three months later.
ALLOCATION_REASONS = (
    "SAFETY",
    "DEFECTIVE",
    "CAMERA_PLATFORM",
    "REDUCED_CAPACITY",
    "CLOSED_SECTOR",
    "SPONSOR",
    "PROTOCOL",
    "PRESS",
    "VIP",
    "AWAY_SUPPORTERS",
    "ACCESSIBILITY",
    "PLAYER_FAMILY",
    "OTHER",
)

DISCOUNT_KINDS = ("PERCENTAGE", "FIXED_AMOUNT")


class TicketType(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """Adult, child, pensioner, VIP, complimentary, away supporter.

    A tenant-level catalogue rather than a per-event list: a club's concession
    policy is a property of the club, and repeating it on every fixture is how
    the child price ends up different in April.
    """

    __tablename__ = "ticket_type"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_ticket_type_tenant_id_id"),
        UniqueConstraint("tenant_id", "code", name="uq_ticket_type_code"),
    )

    name: Mapped[str] = mapped_column(String(80))
    code: Mapped[str] = mapped_column(String(24))
    description: Mapped[str | None] = mapped_column(String(240))

    # Concessions the box office must see proof for. Not enforced online — it
    # is a note for the operator and a line on the ticket.
    requires_proof: Mapped[bool] = mapped_column(default=False)
    # Never charged, and reported outside revenue.
    is_complimentary: Mapped[bool] = mapped_column(default=False)
    # Only sellable to the away allocation.
    is_away: Mapped[bool] = mapped_column(default=False)

    display_order: Mapped[int] = mapped_column(SmallInteger, default=0)
    is_active: Mapped[bool] = mapped_column(default=True)


class TicketedEvent(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """A fixture with tickets on sale.

    Points at the global `match` row when the fixture is in a competition the
    platform knows about, and stands alone when it is not — a friendly, a
    testimonial, a stadium tour. `match_id` has no database foreign key because
    `match` is global and this table is tenant-scoped; the service resolves it.
    """

    __tablename__ = "ticketed_event"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "venue_id"],
            ["venue.tenant_id", "venue.id"],
            name="fk_ticketed_event_venue",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "configuration_id"],
            ["venue_configuration.tenant_id", "venue_configuration.id"],
            name="fk_ticketed_event_configuration",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_ticketed_event_tenant_id_id"),
        UniqueConstraint("tenant_id", "slug", name="uq_ticketed_event_slug"),
        CheckConstraint("status IN " + str(EVENT_STATUSES), name="ticketed_event_status_valid"),
        CheckConstraint(
            "category IN " + str(EVENT_CATEGORIES), name="ticketed_event_category_valid"
        ),
        CheckConstraint(
            "sales_end_at IS NULL OR sales_start_at IS NULL OR sales_end_at > sales_start_at",
            name="ticketed_event_sales_window_ordered",
        ),
        CheckConstraint(
            "max_per_customer > 0", name="ticketed_event_max_per_customer_positive"
        ),
        Index("ix_ticketed_event_kickoff", "tenant_id", "club_id", "kickoff_at"),
        Index("ix_ticketed_event_status", "tenant_id", "club_id", "status"),
    )

    club_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    venue_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    # The configuration this event was *created from*. Kept for provenance
    # only: after the snapshot exists, nothing reads through this to sell.
    configuration_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))

    # Global `match.id`. No FK: `match` is platform reference data and this
    # table is tenant-scoped, so a composite tenant key is impossible and a
    # plain one would cross the boundary the module docstring draws.
    match_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    season_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(200))
    # Filled for fixtures with no global match behind them.
    opponent_name: Mapped[str | None] = mapped_column(String(160))
    competition_label: Mapped[str | None] = mapped_column(String(120))

    kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    doors_open_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    status: Mapped[str] = mapped_column(String(12), default="DRAFT")
    category: Mapped[str] = mapped_column(String(1), default="B")
    # A private event is sellable only through a direct link or the box office:
    # a members' pre-sale, a test match, a sponsor evening.
    is_public: Mapped[bool] = mapped_column(default=True)

    currency: Mapped[str] = mapped_column(String(3), default="RON")

    presale_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sales_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sales_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    max_per_customer: Mapped[int] = mapped_column(SmallInteger, default=10)

    # The "don't strand a single seat" rule, off by default and per event.
    # Deliberately configurable rather than always-on: it is right for a
    # near-full league match and wrong for a sparse midweek cup tie, where it
    # would refuse perfectly good sales to protect a seat nobody wants.
    avoid_orphan_seats: Mapped[bool] = mapped_column(default=False)

    # Fees, in minor units. Per-ticket rides on every admission; per-order once.
    fee_per_ticket_minor: Mapped[int] = mapped_column(Integer, default=0)
    fee_per_order_minor: Mapped[int] = mapped_column(Integer, default=0)

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EventConfigurationSnapshot(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """The stadium as it was when this event was created. Never updated.

    One row per event, holding the entire layout — stands, sections, rows,
    seats, gates, zones and price zones — as JSON. It is the audit answer to
    "what did we sell, and where was it?" years after the master configuration
    has moved on, and it is what the buyer-facing map is drawn from.
    """

    __tablename__ = "event_configuration_snapshot"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["ticketed_event.tenant_id", "ticketed_event.id"],
            name="fk_event_snapshot_event",
            ondelete="CASCADE",
        ),
        # One snapshot per event, forever. Re-snapshotting would be exactly the
        # mutation this table exists to prevent.
        UniqueConstraint("event_id", name="uq_event_snapshot_event"),
    )

    event_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))

    source_configuration_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    source_version: Mapped[int] = mapped_column(SmallInteger)
    source_name: Mapped[str] = mapped_column(String(120))

    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    total_capacity: Mapped[int] = mapped_column(Integer, default=0)


class EventSeatInventory(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """One sellable admission at one event.

    A reserved seat gets a row with `seat_id` set; a general-admission place
    gets a row with `seat_id` null. Modelling GA as rows rather than a counter
    costs storage and buys uniformity: one state machine, one locking rule, one
    query for "what is left", and a GA admission that can be individually
    blocked, allocated or refunded like any other.

    **How double-selling is prevented.** One row per admission per event —
    `UNIQUE (event_id, seat_id)` — means two sold rows for the same seat cannot
    exist. Every transition reads its rows with `SELECT ... FOR UPDATE`, so two
    baskets racing for the last seat serialise: the loser sees `CART_HELD` and
    is refused. The check is in the database transaction, not the browser and
    not the service's memory.
    """

    __tablename__ = "event_seat_inventory"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["ticketed_event.tenant_id", "ticketed_event.id"],
            name="fk_event_inventory_event",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_event_inventory_tenant_id_id"),
        # The anti-double-sell constraint for reserved seating. Null `seat_id`
        # rows (GA) are exempt because Postgres treats nulls as distinct, which
        # is what we want: GA places are interchangeable and have no identity.
        UniqueConstraint("event_id", "seat_id", name="uq_event_inventory_seat"),
        CheckConstraint(
            "state IN " + str(INVENTORY_STATES), name="event_inventory_state_valid"
        ),
        # A hold without an expiry never expires, which is a seat lost forever.
        CheckConstraint(
            "(state = 'CART_HELD') = (hold_expires_at IS NOT NULL)",
            name="event_inventory_hold_has_expiry",
        ),
        # The availability query, and the sweep that expires stale holds.
        Index("ix_event_inventory_available", "tenant_id", "event_id", "section_id", "state"),
        Index("ix_event_inventory_hold_expiry", "state", "hold_expires_at"),
        Index("ix_event_inventory_cart", "tenant_id", "cart_id"),
        Index("ix_event_inventory_order", "tenant_id", "order_id"),
    )

    event_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))

    # Points into the *master* seat, for provenance and for season passes that
    # must land on the same physical seat every match. Deliberately not a
    # foreign key: the master seat may be deleted in a later configuration and
    # this row must survive it intact.
    seat_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    section_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))

    # Labels snapshotted from the master at creation. This is what the ticket
    # prints and what the scanner shows the steward, and it must not change
    # when somebody renames a row next season.
    stand_name: Mapped[str] = mapped_column(String(120))
    section_name: Mapped[str] = mapped_column(String(120))
    section_code: Mapped[str] = mapped_column(String(24))
    section_kind: Mapped[str] = mapped_column(String(24))
    row_label: Mapped[str | None] = mapped_column(String(12))
    seat_label: Mapped[str | None] = mapped_column(String(12))
    seat_kind: Mapped[str] = mapped_column(String(24), default="STANDARD")
    seat_index: Mapped[int] = mapped_column(SmallInteger, default=0)

    # The zone *code*, not the row: prices are resolved against a code so that
    # a snapshot stays readable after the zone is redrawn.
    price_zone_code: Mapped[str | None] = mapped_column(String(24))

    state: Mapped[str] = mapped_column(String(24), default="AVAILABLE")

    # Which concession the buyer chose for this seat, recorded at hold time.
    # It lives here rather than on the cart line because the ordering kernel's
    # line is `(type, reference, quantity)` with nowhere to put it — and
    # because "row G seat 12, child" is a property of the seat being taken,
    # not of the basket it is sitting in.
    ticket_type_code: Mapped[str | None] = mapped_column(String(24))

    # Set only while CART_HELD. The sweep in `maintenance.py` returns expired
    # rows to AVAILABLE; the read path also treats a lapsed hold as free, so a
    # seat is never lost to a sweep that has not run yet.
    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cart_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    order_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    allocation_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))


class Allocation(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """Inventory held back from public sale, and the reason why.

    Two kinds, and the difference is what happens to the capacity:

    - **Hard hold** removes the seats from sellable capacity. A camera
      platform is not "unsold", it is not there.
    - **Soft allocation** keeps them in capacity but assigns them to somebody —
      a sponsor, the press, the away club. It can carry an access code, expire
      by itself, and be released back into public sale, which is how the club
      recovers 200 unclaimed away seats on the Thursday before the match.
    """

    __tablename__ = "allocation"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["ticketed_event.tenant_id", "ticketed_event.id"],
            name="fk_allocation_event",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_allocation_tenant_id_id"),
        CheckConstraint("kind IN " + str(ALLOCATION_KINDS), name="allocation_kind_valid"),
        CheckConstraint("reason IN " + str(ALLOCATION_REASONS), name="allocation_reason_valid"),
        Index("ix_allocation_event", "tenant_id", "event_id", "kind"),
    )

    event_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))

    kind: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(String(24), default="OTHER")
    name: Mapped[str] = mapped_column(String(160))

    # Who it is for, and how they claim it. The code is what a sponsor types to
    # see seats nobody else can — so it is unpredictable, not sequential.
    owner_name: Mapped[str | None] = mapped_column(String(160))
    access_code: Mapped[str | None] = mapped_column(String(32))

    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)

    seat_count: Mapped[int] = mapped_column(Integer, default=0)


class PriceList(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """A set of prices that applies at one of three levels.

    Resolution is EVENT → SEASON → VENUE, first match wins. A club sets a
    default list for the ground once, adjusts it for a season, and overrides
    single fixtures — without ever restating the prices it did not change.
    """

    __tablename__ = "price_list"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_price_list_tenant_id_id"),
        CheckConstraint("scope IN " + str(PRICE_LIST_SCOPES), name="price_list_scope_valid"),
        # Exactly one anchor, matching the scope. A list that claims to be an
        # event override with no event is unresolvable.
        CheckConstraint(
            "(scope = 'VENUE' AND venue_id IS NOT NULL AND season_id IS NULL "
            "  AND event_id IS NULL) OR "
            "(scope = 'SEASON' AND season_id IS NOT NULL AND event_id IS NULL) OR "
            "(scope = 'EVENT' AND event_id IS NOT NULL)",
            name="price_list_anchor_matches_scope",
        ),
        Index(
            "ix_price_list_lookup",
            "tenant_id",
            "scope",
            "event_id",
            "season_id",
            "venue_id",
        ),
    )

    name: Mapped[str] = mapped_column(String(120))
    scope: Mapped[str] = mapped_column(String(12))

    venue_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    season_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    event_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    currency: Mapped[str] = mapped_column(String(3), default="RON")


class PriceRule(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """One cell of the pricing matrix: price zone x ticket type.

    VAT is stored as basis points and with an `is_included` flag rather than as
    a computed net and gross. A club that sells VAT-inclusive and one that adds
    it on top disagree about which number is the real price, and storing the
    derived one loses the answer.
    """

    __tablename__ = "price_rule"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "price_list_id"],
            ["price_list.tenant_id", "price_list.id"],
            name="fk_price_rule_list",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "ticket_type_id"],
            ["ticket_type.tenant_id", "ticket_type.id"],
            name="fk_price_rule_ticket_type",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "price_list_id", "price_zone_code", "ticket_type_id", name="uq_price_rule_cell"
        ),
        CheckConstraint("amount_minor >= 0", name="price_rule_amount_non_negative"),
        CheckConstraint(
            "vat_rate_bp >= 0 AND vat_rate_bp <= 10000", name="price_rule_vat_rate_sane"
        ),
    )

    price_list_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    ticket_type_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    price_zone_code: Mapped[str] = mapped_column(String(24))

    amount_minor: Mapped[int] = mapped_column(Integer)
    # Basis points: 1900 is 19%. Integer because a VAT rate in a float is a
    # rounding error on somebody's invoice.
    vat_rate_bp: Mapped[int] = mapped_column(Integer, default=0)
    vat_included: Mapped[bool] = mapped_column(default=True)
    fee_minor: Mapped[int] = mapped_column(Integer, default=0)


class PromoCode(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """A discount somebody types at checkout.

    Scoped to an event or left open across the club. Usage is counted rather
    than merely capped so that "how many did the radio campaign actually sell"
    is answerable.
    """

    __tablename__ = "promo_code"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_promo_code"),
        CheckConstraint("discount_kind IN " + str(DISCOUNT_KINDS), name="promo_discount_valid"),
        CheckConstraint("discount_value >= 0", name="promo_discount_non_negative"),
        CheckConstraint(
            "max_redemptions IS NULL OR max_redemptions > 0",
            name="promo_max_redemptions_positive",
        ),
    )

    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(120))

    event_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    discount_kind: Mapped[str] = mapped_column(String(16), default="PERCENTAGE")
    # Percent when PERCENTAGE, minor units when FIXED_AMOUNT.
    discount_value: Mapped[int] = mapped_column(Integer, default=0)

    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    max_redemptions: Mapped[int | None] = mapped_column(Integer)
    redemption_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(default=True)
