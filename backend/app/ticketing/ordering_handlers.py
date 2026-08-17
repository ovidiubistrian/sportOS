"""Ticket lines in the ordering kernel.

Registers `TICKET` and `SEASON_TICKET` so a supporter can buy two seats, a
scarf and a membership in one basket and pay once — which is what ADR-0005's
line-handler registry exists to make possible. Nothing in `ordering` learns
what a seat is; it calls `price`, `fulfil` and `reverse` and this module knows
the rest.

A ticket line's `reference_id` is an **`EventSeatInventory` row**, not a
product. That is the natural unit: one line is one admission, the seat is
already chosen, and quantity is always one. It also means the basket and the
seat hold are the same fact recorded once, rather than two that can disagree.

**Where the order id comes from.** The kernel's `fulfil` hook is
`(session, request, club_id)` — deliberately, since most sellable things do not
care which order they belong to. Tickets do: a refund has to find its seats. So
the ticketing checkout calls the kernel, gets the order back, and then binds
the seats to it in the same transaction (see `checkout_tickets` in
`public_router.py`). `fulfil` here does the job it is well placed for — a last
check, under lock, that the hold is still good — and leaves the binding to the
caller that actually knows the order.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import SeatUnavailable, ValidationFailed
from app.core.money import Money
from app.ordering.handlers import LineRequest, PricedLine, register
from app.ticketing.event_models import EventSeatInventory, TicketedEvent
from app.ticketing.inventory import is_free
from app.ticketing.pricing import resolve
from app.ticketing.ticket_models import SeasonTicketProduct


async def _row(
    session: AsyncSession, reference_id: UUID, *, club_id: UUID
) -> tuple[EventSeatInventory, TicketedEvent]:
    row = await session.scalar(
        select(EventSeatInventory).where(EventSeatInventory.id == reference_id)
    )
    if row is None:
        raise ValidationFailed("That seat is not for sale.", field="reference_id")

    event = await session.scalar(select(TicketedEvent).where(TicketedEvent.id == row.event_id))
    # The club check is not redundant with RLS: RLS keeps tenants apart, and
    # this keeps two clubs *inside* one tenant apart, which a multi-club
    # academy genuinely is.
    if event is None or event.club_id != club_id:
        raise ValidationFailed("That seat belongs to another club.", field="reference_id")
    return row, event


class TicketLineHandler:
    """One admission at one match."""

    line_type = "TICKET"

    async def price(
        self, session: AsyncSession, request: LineRequest, *, club_id: UUID
    ) -> PricedLine:
        row, event = await _row(session, request.reference_id, club_id=club_id)

        if request.quantity != 1:
            raise ValidationFailed("A reserved seat is bought one at a time.", field="quantity")
        if event.status != "PUBLISHED":
            raise ValidationFailed("This match is not on sale.", field="reference_id")

        resolved = await resolve(
            session,
            row.tenant_id,
            event,
            zone_code=row.price_zone_code or "",
            ticket_type_code=row.ticket_type_code or "ADULT",
        )

        where = (
            f"{row.stand_name} · {row.section_name}"
            if row.seat_label is None
            else f"{row.stand_name} · {row.section_name} · {row.row_label}{row.seat_label}"
        )
        return PricedLine(
            description=f"{event.name} — {where} ({resolved.ticket_type_name})",
            unit_price=resolved.total,
            quantity=1,
        )

    async def fulfil(
        self, session: AsyncSession, request: LineRequest, *, club_id: UUID
    ) -> None:
        """Last check that the hold is still good, under a row lock.

        The gap between pricing a basket and placing the order is small but not
        zero, and on a sell-out it is exactly where a hold lapses. Catching it
        here means the order fails cleanly instead of issuing a ticket for a
        seat somebody else already has.
        """
        row = await session.scalar(
            select(EventSeatInventory)
            .where(EventSeatInventory.id == request.reference_id)
            .with_for_update()
        )
        if row is None:
            raise SeatUnavailable("That seat is no longer available.")
        if row.state == "CART_HELD" and is_free(row):
            raise SeatUnavailable("Your reservation ran out before checkout completed.")
        if row.state not in ("CART_HELD", "SOLD", "RESERVED"):
            raise SeatUnavailable("Somebody else took that seat while you were paying.")

    async def reverse(
        self, session: AsyncSession, request: LineRequest, *, club_id: UUID
    ) -> None:
        """A cancelled order puts the seat back on sale."""
        row = await session.scalar(
            select(EventSeatInventory)
            .where(EventSeatInventory.id == request.reference_id)
            .with_for_update()
        )
        if row is None:
            return
        if row.state in ("SOLD", "RESERVED", "CART_HELD"):
            row.state = "REFUNDED_RELEASED" if row.state == "SOLD" else "AVAILABLE"
            row.order_id = None
            row.cart_id = None
            row.hold_expires_at = None


class SeasonTicketLineHandler:
    """A season ticket, priced from its product rather than per match."""

    line_type = "SEASON_TICKET"

    async def price(
        self, session: AsyncSession, request: LineRequest, *, club_id: UUID
    ) -> PricedLine:
        product = await session.scalar(
            select(SeasonTicketProduct).where(SeasonTicketProduct.id == request.reference_id)
        )
        if product is None or product.club_id != club_id:
            raise ValidationFailed("That season ticket is not for sale.", field="reference_id")
        if product.status != "ON_SALE":
            raise ValidationFailed("That season ticket is not on sale.", field="reference_id")

        return PricedLine(
            description=product.name,
            unit_price=Money(product.price_minor, product.currency),
            quantity=request.quantity,
        )

    async def fulfil(
        self, session: AsyncSession, request: LineRequest, *, club_id: UUID
    ) -> None:
        """No-op: the seat is reserved by `issuing.issue_season_pass`.

        A season pass needs a seat chosen by the buyer, which the kernel's line
        cannot carry, so the ticketing checkout does the work where it has both
        the seat and the order.
        """

    async def reverse(
        self, session: AsyncSession, request: LineRequest, *, club_id: UUID
    ) -> None:
        """Cancelling is a per-pass operation, handled by the ticketing service."""


register(TicketLineHandler())
register(SeasonTicketLineHandler())
