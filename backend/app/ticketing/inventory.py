"""The inventory state machine, and the locking that makes it safe.

Everything that can give a seat to somebody, or take it back, is here — so
there is exactly one place where the rule "a seat is sold once" lives.

**How the guarantee is actually obtained.** Every transition selects its rows
with `SELECT ... FOR UPDATE`, ordered by primary key. Two baskets reaching for
the last seat serialise on the row lock: the first sets `CART_HELD` and
commits, the second wakes up, re-reads the row it is holding a lock on, sees a
live hold and is refused with `SeatUnavailable`. There is no window between the
read and the write for the two to interleave, because there is no separate
read.

The `ORDER BY id` matters as much as the `FOR UPDATE`. Two carts asking for
seats {A, B} and {B, A} without a deterministic lock order will deadlock under
load; with one, the second simply waits.

**Holds expire, and expiry is not a background job's opinion.** A hold carries
`hold_expires_at`, and every read path treats a lapsed hold as free. The sweep
in `maintenance.py` tidies the rows so reports and counts stay honest, but a
seat is never lost because the sweep has not run yet.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, SeatUnavailable, ValidationFailed
from app.ticketing.event_models import EventSeatInventory, TicketedEvent

# How long a basket keeps a seat. Ten minutes is the specified figure and it is
# a genuine trade-off: long enough to find a card, short enough that a sell-out
# is not paralysed by abandoned baskets.
HOLD_TTL = timedelta(minutes=10)

# States a seat can be taken from and given to somebody. `REFUNDED_RELEASED` is
# here because a refunded seat is genuinely back on sale; it stays a distinct
# state only so reporting can tell it from one never sold.
FREE_STATES = ("AVAILABLE", "REFUNDED_RELEASED")


def _now() -> datetime:
    return datetime.now(UTC)


def is_free(row: EventSeatInventory, *, now: datetime | None = None) -> bool:
    """Whether this row may be taken, treating a lapsed hold as free."""
    if row.state in FREE_STATES:
        return True
    if row.state == "CART_HELD" and row.hold_expires_at is not None:
        return row.hold_expires_at <= (now or _now())
    return False


def free_predicate(now: datetime):
    """The same rule as `is_free`, expressed for SQL.

    Kept beside its Python twin deliberately: if the two ever disagree, the
    availability count on the map stops matching what the checkout will accept,
    and a supporter is told a seat is free and then refused it.
    """
    return or_(
        EventSeatInventory.state.in_(FREE_STATES),
        and_(
            EventSeatInventory.state == "CART_HELD",
            EventSeatInventory.hold_expires_at <= now,
        ),
    )


async def hold(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    event_id: UUID,
    cart_id: UUID,
    inventory_ids: list[UUID],
    ticket_type_code: str | None = None,
    ttl: timedelta = HOLD_TTL,
) -> list[EventSeatInventory]:
    """Put seats in a basket for ten minutes, or refuse the lot.

    All or nothing. A partial hold would hand somebody two of the three seats
    they asked for and leave them to notice, which is worse than a clean
    refusal they can act on.
    """
    if not inventory_ids:
        raise ValidationFailed("No seats were selected.", field="seats")

    event = await session.scalar(
        select(TicketedEvent).where(
            TicketedEvent.tenant_id == tenant_id, TicketedEvent.id == event_id
        )
    )
    if event is None:
        raise ValidationFailed("That match does not exist.", field="event_id")
    if len(inventory_ids) > event.max_per_customer:
        raise ValidationFailed(
            f"This match is limited to {event.max_per_customer} tickets per person.",
            field="seats",
            limit=event.max_per_customer,
        )

    now = _now()
    # Deterministic lock order — see the module note on deadlocks.
    rows = list(
        await session.scalars(
            select(EventSeatInventory)
            .where(
                EventSeatInventory.tenant_id == tenant_id,
                EventSeatInventory.event_id == event_id,
                EventSeatInventory.id.in_(inventory_ids),
            )
            .order_by(EventSeatInventory.id)
            .with_for_update()
        )
    )

    if len(rows) != len(set(inventory_ids)):
        raise SeatUnavailable("Some of those seats are not part of this match.")

    taken = [row for row in rows if not is_free(row, now=now)]
    if taken:
        raise SeatUnavailable(
            "Somebody else took one of those seats while you were choosing.",
            seats=[_describe(row) for row in taken],
        )

    if event.avoid_orphan_seats:
        await _refuse_if_stranding(session, tenant_id, event_id, rows, now=now)

    expires = now + ttl
    for row in rows:
        row.state = "CART_HELD"
        row.hold_expires_at = expires
        row.cart_id = cart_id
        row.order_id = None
        if ticket_type_code:
            row.ticket_type_code = ticket_type_code
    await session.flush()
    return rows


async def extend_hold(
    session: AsyncSession, tenant_id: UUID, cart_id: UUID, *, ttl: timedelta = HOLD_TTL
) -> datetime:
    """Push the countdown back — used when a basket is actively being edited."""
    expires = _now() + ttl
    await session.execute(
        update(EventSeatInventory)
        .where(
            EventSeatInventory.tenant_id == tenant_id,
            EventSeatInventory.cart_id == cart_id,
            EventSeatInventory.state == "CART_HELD",
        )
        .values(hold_expires_at=expires)
    )
    return expires


async def release_cart(
    session: AsyncSession, tenant_id: UUID, cart_id: UUID, *, only: list[UUID] | None = None
) -> int:
    """Give seats back. Used when a basket is emptied, edited or abandoned."""
    conditions = [
        EventSeatInventory.tenant_id == tenant_id,
        EventSeatInventory.cart_id == cart_id,
        EventSeatInventory.state == "CART_HELD",
    ]
    if only:
        conditions.append(EventSeatInventory.id.in_(only))

    result = await session.execute(
        update(EventSeatInventory)
        .where(*conditions)
        .values(state="AVAILABLE", hold_expires_at=None, cart_id=None)
    )
    return int(result.rowcount or 0)


async def confirm_sold(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    cart_id: UUID,
    order_id: UUID,
    event_id: UUID | None = None,
) -> list[EventSeatInventory]:
    """Turn a basket's holds into sales.

    Re-locks and re-checks rather than trusting the earlier hold. Between the
    hold and the payment there is a network round trip to a bank, which is long
    enough for the hold to expire and the seat to be sold to somebody else —
    and finding that out here, before a ticket exists, is the whole point.
    """
    conditions = [
        EventSeatInventory.tenant_id == tenant_id,
        EventSeatInventory.cart_id == cart_id,
    ]
    if event_id is not None:
        conditions.append(EventSeatInventory.event_id == event_id)

    rows = list(
        await session.scalars(
            select(EventSeatInventory)
            .where(*conditions)
            .order_by(EventSeatInventory.id)
            .with_for_update()
        )
    )
    if not rows:
        raise SeatUnavailable("That basket no longer holds any seats.")

    now = _now()
    lost = [
        row
        for row in rows
        if row.state != "CART_HELD"
        or (row.hold_expires_at is not None and row.hold_expires_at <= now)
    ]
    if lost:
        raise SeatUnavailable(
            "Your reservation ran out before the payment completed.",
            seats=[_describe(row) for row in lost],
        )

    for row in rows:
        row.state = "SOLD"
        row.order_id = order_id
        row.hold_expires_at = None
    await session.flush()
    return rows


async def release_sold(
    session: AsyncSession, tenant_id: UUID, *, order_id: UUID, refunded: bool = True
) -> int:
    """Put seats back after a cancellation or refund."""
    result = await session.execute(
        update(EventSeatInventory)
        .where(
            EventSeatInventory.tenant_id == tenant_id,
            EventSeatInventory.order_id == order_id,
            EventSeatInventory.state.in_(("SOLD", "RESERVED", "COMPLIMENTARY")),
        )
        .values(
            state="REFUNDED_RELEASED" if refunded else "AVAILABLE",
            order_id=None,
            cart_id=None,
            hold_expires_at=None,
        )
    )
    return int(result.rowcount or 0)


async def expire_holds(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Return lapsed baskets to sale.

    Runs across tenants, so it is called from the maintenance task with RLS
    disabled rather than from a request.
    """
    result = await session.execute(
        update(EventSeatInventory)
        .where(
            EventSeatInventory.state == "CART_HELD",
            EventSeatInventory.hold_expires_at <= (now or _now()),
        )
        .values(state="AVAILABLE", hold_expires_at=None, cart_id=None)
    )
    return int(result.rowcount or 0)


async def best_available(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    event_id: UUID,
    quantity: int,
    section_id: UUID | None = None,
    price_zone_code: str | None = None,
) -> list[EventSeatInventory]:
    """Find `quantity` seats, together in a row if that is possible.

    Adjacency is the point. Offering a family of four seats scattered across
    three stands is technically an answer and practically useless, so the
    search prefers a contiguous block and only falls back to loose seats when
    no block exists.
    """
    if quantity < 1:
        raise ValidationFailed("Ask for at least one seat.", field="quantity")

    now = _now()
    conditions = [
        EventSeatInventory.tenant_id == tenant_id,
        EventSeatInventory.event_id == event_id,
        free_predicate(now),
    ]
    if section_id is not None:
        conditions.append(EventSeatInventory.section_id == section_id)
    if price_zone_code is not None:
        conditions.append(EventSeatInventory.price_zone_code == price_zone_code)

    candidates = list(
        await session.scalars(
            select(EventSeatInventory)
            .where(*conditions)
            .order_by(
                EventSeatInventory.section_id,
                EventSeatInventory.row_label,
                EventSeatInventory.seat_index,
            )
        )
    )
    if len(candidates) < quantity:
        raise SeatUnavailable(
            f"There are not {quantity} seats left in that part of the ground."
        )

    # General admission has no adjacency to speak of — any places will do.
    if candidates[0].section_kind == "GENERAL_ADMISSION":
        return candidates[:quantity]

    best: list[EventSeatInventory] = []
    run: list[EventSeatInventory] = []
    for row in candidates:
        if run and (
            row.section_id != run[-1].section_id
            or row.row_label != run[-1].row_label
            or row.seat_index != run[-1].seat_index + 1
        ):
            run = []
        run.append(row)
        if len(run) == quantity:
            best = list(run)
            break

    return best or candidates[:quantity]


async def set_state(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    event_id: UUID,
    inventory_ids: list[UUID],
    state: str,
    allocation_id: UUID | None = None,
) -> int:
    """Move seats into a held or allocated state, under lock.

    Used by hard holds and soft allocations. Refuses to touch anything already
    sold: a club closing a stand for safety after 300 people have bought into
    it has a refund problem, not a data-entry problem, and quietly overwriting
    those rows would hide it.
    """
    rows = list(
        await session.scalars(
            select(EventSeatInventory)
            .where(
                EventSeatInventory.tenant_id == tenant_id,
                EventSeatInventory.event_id == event_id,
                EventSeatInventory.id.in_(inventory_ids),
            )
            .order_by(EventSeatInventory.id)
            .with_for_update()
        )
    )

    occupied = [row for row in rows if row.state in ("SOLD", "COMPLIMENTARY", "RESERVED")]
    if occupied:
        raise Conflict(
            "Some of those seats have already been sold.",
            seats=[_describe(row) for row in occupied],
        )

    for row in rows:
        row.state = state
        row.allocation_id = allocation_id
        row.hold_expires_at = None
        row.cart_id = None
    await session.flush()
    return len(rows)


async def release_allocation(
    session: AsyncSession, tenant_id: UUID, *, allocation_id: UUID
) -> int:
    """Return an allocation's unclaimed seats to public sale."""
    result = await session.execute(
        update(EventSeatInventory)
        .where(
            EventSeatInventory.tenant_id == tenant_id,
            EventSeatInventory.allocation_id == allocation_id,
            EventSeatInventory.state.in_(("SOFT_ALLOCATED", "HARD_BLOCKED")),
        )
        .values(state="AVAILABLE", allocation_id=None)
    )
    return int(result.rowcount or 0)


async def availability_by_section(
    session: AsyncSession, tenant_id: UUID, event_id: UUID
) -> list[dict]:
    """What the buyer-facing map colours each sector with."""
    now = _now()
    rows = (
        await session.execute(
            select(
                EventSeatInventory.section_id,
                EventSeatInventory.section_code,
                EventSeatInventory.section_name,
                EventSeatInventory.stand_name,
                EventSeatInventory.section_kind,
                EventSeatInventory.price_zone_code,
                func.count(),
                func.count().filter(free_predicate(now)),
            )
            .where(
                EventSeatInventory.tenant_id == tenant_id,
                EventSeatInventory.event_id == event_id,
            )
            .group_by(
                EventSeatInventory.section_id,
                EventSeatInventory.section_code,
                EventSeatInventory.section_name,
                EventSeatInventory.stand_name,
                EventSeatInventory.section_kind,
                EventSeatInventory.price_zone_code,
            )
            .order_by(EventSeatInventory.stand_name, EventSeatInventory.section_name)
        )
    ).all()

    return [
        {
            "section_id": str(section_id),
            "code": code,
            "name": name,
            "stand": stand,
            "kind": kind,
            "price_zone_code": zone,
            "total": total,
            "available": available,
        }
        for section_id, code, name, stand, kind, zone, total, available in rows
    ]


# --- internals -------------------------------------------------------------


def _describe(row: EventSeatInventory) -> str:
    if row.seat_label is None:
        return f"{row.stand_name} · {row.section_name}"
    return f"{row.stand_name} · {row.section_name} · {row.row_label}{row.seat_label}"


async def _refuse_if_stranding(
    session: AsyncSession,
    tenant_id: UUID,
    event_id: UUID,
    taking: list[EventSeatInventory],
    *,
    now: datetime,
) -> None:
    """The optional "don't leave a single seat behind" rule.

    Off by default and per event — see `TicketedEvent.avoid_orphan_seats`. It
    is right for a near-full league match, where a stranded single seat is a
    seat nobody buys, and wrong for a sparse midweek tie, where it would refuse
    good sales to protect seats that were never going to sell anyway.

    Only ever applied to reserved seating, and only within the rows actually
    being taken from.
    """
    affected = {
        (row.section_id, row.row_label)
        for row in taking
        if row.section_kind == "RESERVED" and row.row_label is not None
    }
    if not affected:
        return

    taking_ids = {row.id for row in taking}
    for section_id, row_label in affected:
        seats = list(
            await session.scalars(
                select(EventSeatInventory)
                .where(
                    EventSeatInventory.tenant_id == tenant_id,
                    EventSeatInventory.event_id == event_id,
                    EventSeatInventory.section_id == section_id,
                    EventSeatInventory.row_label == row_label,
                )
                .order_by(EventSeatInventory.seat_index)
            )
        )
        # After this basket, which seats would still be free?
        free_after = [seat.id not in taking_ids and is_free(seat, now=now) for seat in seats]
        for index, still_free in enumerate(free_after):
            if not still_free:
                continue
            left_taken = index == 0 or not free_after[index - 1]
            right_taken = index == len(free_after) - 1 or not free_after[index + 1]
            if left_taken and right_taken:
                raise SeatUnavailable(
                    "Choosing those seats would leave a single seat on its own. "
                    "Please shift your selection by one.",
                    rule="AVOID_ORPHAN_SEATS",
                    row=f"{row_label}{seats[index].seat_label}",
                )
