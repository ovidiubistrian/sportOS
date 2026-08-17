"""The stadium master: venues and their versioned configurations.

This is the *drawing* of a stadium, not the inventory of any match. Nothing in
this module is ever sold. A match takes a frozen copy at creation time (see
`event_models.EventConfigurationSnapshot`), and that separation is the rule the
whole ticketing module is built around: redrawing a stand in March must not
move somebody who bought a seat in January.

The shape is venue → configuration → stand → section → row → seat, with gates
and price zones hanging off the configuration:

    venue ─── venue_configuration ─┬─ stand ─── section ─── seat_row ─── seat
                                   ├─ gate ─── gate_section ──┘
                                   ├─ access_zone
                                   └─ price_zone

**Why the configuration, and not the venue, owns everything below it.** A club
plays a league match at full capacity, a European tie with the away end closed
and a cup match with a temporary stand. Those are not three stadiums; they are
three configurations of one. Hanging stands off the venue would force the club
to either duplicate the venue or mutate it between matches — and mutating it is
precisely what must never happen once tickets exist.

Every child points at its parent through a **composite** foreign key carrying
`tenant_id`. A single-column reference would let a row name a parent in another
tenant and the database would accept it; RLS hides the row but does not stop
the write. With `(tenant_id, parent_id)` the cross-tenant reference is not
merely denied, it is unrepresentable.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantScoped, Timestamped, UUIDPrimaryKey

# Which way the pitch lies. Only used to orient the editor's drawing, so the
# stands a supporter sees on screen sit where they sit in the ground.
PITCH_ORIENTATIONS = ("NORTH_SOUTH", "NORTHEAST_SOUTHWEST", "EAST_WEST", "NORTHWEST_SOUTHEAST")

# A configuration's life. The transition that matters is DRAFT → PUBLISHED:
# after it, the rows below are frozen and editing forks a new draft.
CONFIGURATION_STATUSES = ("DRAFT", "PUBLISHED", "ARCHIVED")

# What a section sells. RESERVED has rows and numbered seats and is picked from
# a map; GENERAL_ADMISSION has a capacity and no seat identity at all.
SECTION_KINDS = ("RESERVED", "GENERAL_ADMISSION")

# Why a seat is not an ordinary seat. Kept on the seat rather than in a flag
# soup because a wheelchair space and its companion seat must be *sold*
# differently, not merely displayed differently.
SEAT_KINDS = ("STANDARD", "WHEELCHAIR", "COMPANION", "OBSTRUCTED_VIEW")

# What a gate is for. Drives which credential may pass through it and what the
# steward sees on the scanner.
GATE_KINDS = ("PUBLIC", "VIP", "MEDIA", "STAFF", "ACCESSIBLE", "AWAY")

# Which supporters a gate admits. Segregation is a safety requirement at a
# derby, not a preference, so it lives on the gate and is enforced at the scan.
SUPPORTER_SIDES = ("ANY", "HOME", "AWAY")


class Venue(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """A ground the club plays in.

    Deliberately not modelled as a column on the tenant. A club can own a
    stadium and also sell tickets for a training-ground friendly or a cup tie
    at a neighbour's ground, and a one-to-one would have to be undone the first
    time that happened.
    """

    __tablename__ = "venue"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_venue_tenant_id_id"),
        UniqueConstraint("tenant_id", "code", name="uq_venue_code"),
        CheckConstraint(
            "pitch_orientation IN " + str(PITCH_ORIENTATIONS),
            name="venue_pitch_orientation_valid",
        ),
        CheckConstraint("expected_capacity >= 0", name="venue_capacity_non_negative"),
        Index("ix_venue_club", "tenant_id", "club_id"),
    )

    club_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))

    name: Mapped[str] = mapped_column(String(160))
    # The club's own short handle for the ground, used on printed tickets and
    # in exports. Unique per tenant so it can be typed instead of picked.
    code: Mapped[str] = mapped_column(String(24))

    address: Mapped[str | None] = mapped_column(String(240))
    city: Mapped[str | None] = mapped_column(String(120))
    country_code: Mapped[str] = mapped_column(String(2), default="RO")
    # Kick-off is stored in UTC everywhere; this is what turns it back into the
    # time printed on the ticket. A ground, not a club, carries it: a club
    # playing a European away tie needs the *host* ground's zone.
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Bucharest")
    currency: Mapped[str] = mapped_column(String(3), default="RON")

    expected_capacity: Mapped[int] = mapped_column(Integer, default=0)
    pitch_orientation: Mapped[str] = mapped_column(String(24), default="NORTH_SOUTH")

    cover_media_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))


class VenueConfiguration(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """One versioned layout of a venue — the unit that gets published.

    `status` is the whole point. A DRAFT is freely editable. A PUBLISHED
    configuration is immutable: the service layer refuses writes to it and to
    everything beneath it, and editing produces a new draft at the next version
    number. ARCHIVED is a published one taken out of use, kept because matches
    already snapshotted from it must stay readable.

    Immutability is enforced in the service rather than by a database trigger
    so that the refusal arrives as a domain error a screen can explain, instead
    of a constraint violation the API has to guess at.
    """

    __tablename__ = "venue_configuration"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "venue_id"],
            ["venue.tenant_id", "venue.id"],
            name="fk_venue_configuration_venue",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_venue_configuration_tenant_id_id"),
        UniqueConstraint("venue_id", "name", "version", name="uq_venue_configuration_version"),
        CheckConstraint(
            "status IN " + str(CONFIGURATION_STATUSES), name="venue_configuration_status_valid"
        ),
        CheckConstraint("version >= 1", name="venue_configuration_version_positive"),
        CheckConstraint(
            "(status = 'DRAFT') = (published_at IS NULL)",
            name="venue_configuration_published_at_matches_status",
        ),
        Index("ix_venue_configuration_venue", "tenant_id", "venue_id", "status"),
    )

    venue_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))

    # "Football — standard", "Concert", "Renovation 2027". The name identifies
    # the *intent*; the version identifies the revision of it.
    name: Mapped[str] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(SmallInteger, default=1)
    status: Mapped[str] = mapped_column(String(12), default="DRAFT")

    valid_from: Mapped[date | None] = mapped_column(Date)

    # Computed from the sections at publish time and stored, so a capacity
    # report over ten seasons does not have to re-walk ten layouts.
    total_capacity: Mapped[int] = mapped_column(Integer, default=0)

    created_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Set when this draft was forked from a published version, so the history
    # of a layout is walkable.
    forked_from_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))


class PriceZone(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """A colour-coded band of the ground that shares a price.

    Category 1, VIP, Away. It belongs to the configuration rather than to the
    tenant because which parts of the ground are premium changes with the
    layout — the away end is Category 2 for a league match and its own zone for
    a derby.
    """

    __tablename__ = "price_zone"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "configuration_id"],
            ["venue_configuration.tenant_id", "venue_configuration.id"],
            name="fk_price_zone_configuration",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_price_zone_tenant_id_id"),
        UniqueConstraint("configuration_id", "code", name="uq_price_zone_code"),
    )

    configuration_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(80))
    # Stable handle. Price rules and event snapshots reference the *code*, not
    # the row, so a price list survives the zone being redrawn next season.
    code: Mapped[str] = mapped_column(String(24))
    # Hex, drawn on the map and in the legend. Colour is data, not styling: the
    # club decides that VIP is gold, and the buyer-facing map must agree with
    # the admin one.
    colour: Mapped[str] = mapped_column(String(9), default="#334155")
    display_order: Mapped[int] = mapped_column(SmallInteger, default=0)


class Stand(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """A side of the ground — Main, North, South, Away."""

    __tablename__ = "stand"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "configuration_id"],
            ["venue_configuration.tenant_id", "venue_configuration.id"],
            name="fk_stand_configuration",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_stand_tenant_id_id"),
        UniqueConstraint("configuration_id", "code", name="uq_stand_code"),
    )

    configuration_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(24))
    display_order: Mapped[int] = mapped_column(SmallInteger, default=0)

    # The polygon drawn in the editor: {"points": [[x, y], ...]} in an abstract
    # 1000x1000 space with the pitch at the centre. JSON rather than columns
    # because the shape is read and written whole, never queried into, and a
    # trapezoid today may be an arc tomorrow.
    geometry: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class Section(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """A sector within a stand — the unit a gate serves and a price zone covers.

    `kind` decides whether it has seats at all. A RESERVED section's capacity is
    derived from its seats and kept in step by the service; a GENERAL_ADMISSION
    section has no seats and `declared_capacity` is the truth.
    """

    __tablename__ = "section"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "stand_id"],
            ["stand.tenant_id", "stand.id"],
            name="fk_section_stand",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "price_zone_id"],
            ["price_zone.tenant_id", "price_zone.id"],
            name="fk_section_price_zone",
            # Names the column explicitly: a bare SET NULL on a composite key
            # nulls *every* column in it, `tenant_id` included, and that column
            # is NOT NULL. Postgres 15+ allows the narrower form; without it,
            # deleting a price zone fails with a constraint violation that
            # points at the wrong table entirely.
            ondelete="SET NULL (price_zone_id)",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_section_tenant_id_id"),
        UniqueConstraint("stand_id", "code", name="uq_section_code"),
        CheckConstraint("kind IN " + str(SECTION_KINDS), name="section_kind_valid"),
        CheckConstraint("declared_capacity >= 0", name="section_capacity_non_negative"),
    )

    stand_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    price_zone_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(24))
    kind: Mapped[str] = mapped_column(String(24), default="RESERVED")

    # For GA this is the capacity. For reserved seating it is what the club
    # *expects*, and the review step reports the difference against the seats
    # actually generated — a mismatch is usually a generator run with the wrong
    # numbers, and it is much cheaper to catch here than at the turnstile.
    declared_capacity: Mapped[int] = mapped_column(Integer, default=0)

    display_order: Mapped[int] = mapped_column(SmallInteger, default=0)
    geometry: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class SeatRow(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """A row of seats. Only reserved sections have them."""

    __tablename__ = "seat_row"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "section_id"],
            ["section.tenant_id", "section.id"],
            name="fk_seat_row_section",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_seat_row_tenant_id_id"),
        # "Two rows called G in the same sector" is a stewarding problem on
        # matchday, so it is a constraint rather than a validation warning.
        UniqueConstraint("section_id", "label", name="uq_seat_row_label"),
    )

    section_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    label: Mapped[str] = mapped_column(String(12))
    display_order: Mapped[int] = mapped_column(SmallInteger, default=0)


class Seat(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """One seat, with a permanent identity.

    The UUID is the seat; the row and number are only what is painted on it. A
    club that renumbers a stand keeps every historical sale attached to the
    right physical seat, which a "Row G, seat 12" string key could never do.

    A seat can carry its own price zone, overriding its section's — that is how
    the first three rows of a stand become Category 1 without splitting the
    sector in two.
    """

    __tablename__ = "seat"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "section_id"],
            ["section.tenant_id", "section.id"],
            name="fk_seat_section",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "row_id"],
            ["seat_row.tenant_id", "seat_row.id"],
            name="fk_seat_row",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "price_zone_id"],
            ["price_zone.tenant_id", "price_zone.id"],
            name="fk_seat_price_zone",
            # Names the column explicitly: a bare SET NULL on a composite key
            # nulls *every* column in it, `tenant_id` included, and that column
            # is NOT NULL. Postgres 15+ allows the narrower form; without it,
            # deleting a price zone fails with a constraint violation that
            # points at the wrong table entirely.
            ondelete="SET NULL (price_zone_id)",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_seat_tenant_id_id"),
        UniqueConstraint("row_id", "label", name="uq_seat_label"),
        CheckConstraint("kind IN " + str(SEAT_KINDS), name="seat_kind_valid"),
        Index("ix_seat_section", "tenant_id", "section_id"),
    )

    section_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    row_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    price_zone_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    label: Mapped[str] = mapped_column(String(12))
    kind: Mapped[str] = mapped_column(String(24), default="STANDARD")

    # Blocked in the *master*: a seat that physically does not exist any more,
    # or one permanently behind a pillar. Distinct from a hard hold on a single
    # match, which lives on the event inventory.
    is_blocked: Mapped[bool] = mapped_column(default=False)

    # Position within the row, used to lay the seat out and — more importantly
    # — to decide what "two seats together" means when the buyer asks for it.
    seat_index: Mapped[int] = mapped_column(SmallInteger, default=0)


class AccessZone(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """A part of the ground reachable once through a given gate.

    Separate from the price zone on purpose: what a ticket *costs* and where it
    lets you walk are different questions. A VIP seat and a press seat may cost
    nothing alike and still share the west concourse.
    """

    __tablename__ = "access_zone"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "configuration_id"],
            ["venue_configuration.tenant_id", "venue_configuration.id"],
            name="fk_access_zone_configuration",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_access_zone_tenant_id_id"),
        UniqueConstraint("configuration_id", "code", name="uq_access_zone_code"),
    )

    configuration_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(24))


class Gate(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """A way in, and the rules about who may use it."""

    __tablename__ = "gate"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "configuration_id"],
            ["venue_configuration.tenant_id", "venue_configuration.id"],
            name="fk_gate_configuration",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "access_zone_id"],
            ["access_zone.tenant_id", "access_zone.id"],
            name="fk_gate_access_zone",
            # Names the column explicitly: a bare SET NULL on a composite key
            # nulls *every* column in it, `tenant_id` included, and that column
            # is NOT NULL. Postgres 15+ allows the narrower form; without it,
            # deleting a price zone fails with a constraint violation that
            # points at the wrong table entirely.
            ondelete="SET NULL (access_zone_id)",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_gate_tenant_id_id"),
        UniqueConstraint("configuration_id", "code", name="uq_gate_code"),
        CheckConstraint("kind IN " + str(GATE_KINDS), name="gate_kind_valid"),
        CheckConstraint(
            "supporter_side IN " + str(SUPPORTER_SIDES), name="gate_supporter_side_valid"
        ),
    )

    configuration_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    access_zone_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    name: Mapped[str] = mapped_column(String(120))
    # Painted on the ground and printed on the ticket: "Gate C".
    code: Mapped[str] = mapped_column(String(24))
    kind: Mapped[str] = mapped_column(String(24), default="PUBLIC")
    supporter_side: Mapped[str] = mapped_column(String(8), default="ANY")

    is_accessible: Mapped[bool] = mapped_column(default=False)
    note: Mapped[str | None] = mapped_column(Text)


class GateSection(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """Which sectors a gate admits to.

    A join table because it is genuinely many-to-many: one gate serves several
    sectors, and a sector on a corner is reachable from two gates. The review
    step reports gates with no sectors and sectors with no gate — either one is
    a queue nobody can get through on matchday.
    """

    __tablename__ = "gate_section"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "gate_id"],
            ["gate.tenant_id", "gate.id"],
            name="fk_gate_section_gate",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "section_id"],
            ["section.tenant_id", "section.id"],
            name="fk_gate_section_section",
            ondelete="CASCADE",
        ),
        UniqueConstraint("gate_id", "section_id", name="uq_gate_section"),
    )

    gate_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    section_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
