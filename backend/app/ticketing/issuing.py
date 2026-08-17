"""Turning sold inventory into entitlements, tickets and QR credentials.

One function does the work — `issue_for_order` — and it runs inside the same
transaction as the sale. If minting a credential fails, the order does not
half-exist with three tickets out of four; the whole thing rolls back and the
seats stay held.

The season-pass path is the interesting one. `issue_season_pass` reserves the
*same physical seat* across every included match and mints a separate
entitlement and ticket for each. Twenty matches means twenty tickets and twenty
QR codes, which is the point: releasing match fourteen back to the club touches
one entitlement and leaves the other nineteen untouched.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, SeatUnavailable, ValidationFailed
from app.ticketing import credentials as credential_service
from app.ticketing.event_models import EventSeatInventory, TicketedEvent, TicketType
from app.ticketing.ticket_models import (
    EventEntitlement,
    SeasonPass,
    SeasonTicketEvent,
    SeasonTicketProduct,
    Ticket,
)

# Ticket numbers are human-facing and read down a phone line, so they avoid
# characters that are misheard or misread: no I, O, 0, 1.
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _ticket_number(prefix: str = "T") -> str:
    body = "".join(secrets.choice(_ALPHABET) for _ in range(9))
    return f"{prefix}{body}"


def _reference(prefix: str = "SP") -> str:
    body = "".join(secrets.choice(_ALPHABET) for _ in range(8))
    return f"{prefix}{body}"


async def _gate_codes_for_section(
    session: AsyncSession, tenant_id: UUID, event_id: UUID, section_id: UUID
) -> str:
    """Which gates serve a sector, read from the event's own snapshot.

    From the snapshot rather than the live layout, for the reason the whole
    module exists: a gate reassigned next month must not change which turnstile
    a ticket sold today opens.
    """
    from app.ticketing.event_service import get_snapshot

    snapshot = await get_snapshot(session, tenant_id, event_id)
    wanted = str(section_id)
    codes = [
        gate["code"]
        for gate in snapshot.payload.get("gates", [])
        if wanted in gate.get("section_ids", [])
    ]
    return ",".join(sorted(codes))


async def issue_for_order(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    order_id: UUID,
    holder_name: str | None = None,
    supporter_id: UUID | None = None,
    complimentary: bool = False,
) -> list[Ticket]:
    """Mint an entitlement, ticket and credential for every seat on an order."""
    from app.ticketing.pricing import resolve

    rows = list(
        await session.scalars(
            select(EventSeatInventory).where(
                EventSeatInventory.tenant_id == tenant_id,
                EventSeatInventory.order_id == order_id,
                EventSeatInventory.state.in_(("SOLD", "COMPLIMENTARY")),
            )
        )
    )
    if not rows:
        return []

    issued: list[Ticket] = []
    events: dict[UUID, TicketedEvent] = {}

    for row in rows:
        # An order that is issued twice would mint a second QR for a seat that
        # already has a live one. The unique constraint on `inventory_id` would
        # catch it, but answering early keeps the error readable.
        already = await session.scalar(
            select(EventEntitlement).where(
                EventEntitlement.tenant_id == tenant_id,
                EventEntitlement.inventory_id == row.id,
            )
        )
        if already is not None:
            continue

        event = events.get(row.event_id)
        if event is None:
            event = await session.scalar(
                select(TicketedEvent).where(
                    TicketedEvent.tenant_id == tenant_id, TicketedEvent.id == row.event_id
                )
            )
            if event is None:
                raise NotFound("That match does not exist.")
            events[row.event_id] = event

        type_code = row.ticket_type_code or "ADULT"
        ticket_type = await session.scalar(
            select(TicketType).where(
                TicketType.tenant_id == tenant_id, TicketType.code == type_code
            )
        )

        if complimentary or (ticket_type is not None and ticket_type.is_complimentary):
            price_minor, vat_minor, fee_minor = 0, 0, 0
            currency = event.currency
        else:
            price = await resolve(
                session,
                tenant_id,
                event,
                zone_code=row.price_zone_code or "",
                ticket_type_code=type_code,
            )
            price_minor = price.amount.amount_minor
            vat_minor = price.vat.amount_minor
            fee_minor = price.fee.amount_minor
            currency = price.amount.currency

        entitlement = EventEntitlement(
            tenant_id=tenant_id,
            event_id=row.event_id,
            inventory_id=row.id,
            source="COMPLIMENTARY" if complimentary else "SINGLE",
            status="ACTIVE",
            order_id=order_id,
            ticket_type_code=type_code,
            holder_name=holder_name,
            supporter_id=supporter_id,
        )
        session.add(entitlement)
        await session.flush()

        ticket = Ticket(
            tenant_id=tenant_id,
            event_id=row.event_id,
            entitlement_id=entitlement.id,
            ticket_number=_ticket_number(),
            status="ISSUED",
            ticket_type_code=type_code,
            ticket_type_name=ticket_type.name if ticket_type else type_code.title(),
            currency=currency,
            price_minor=price_minor,
            vat_minor=vat_minor,
            fee_minor=fee_minor,
            order_id=order_id,
            holder_name=holder_name,
            issued_at=datetime.now(UTC),
        )
        session.add(ticket)
        await session.flush()

        await credential_service.mint(
            session,
            tenant_id,
            ticket=ticket,
            event_id=row.event_id,
            section_code=row.section_code,
            gate_codes=await _gate_codes_for_section(
                session, tenant_id, row.event_id, row.section_id
            ),
            valid_from=event.doors_open_at,
            valid_until=None,
        )
        issued.append(ticket)

    return issued


async def issue_season_pass(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    product_id: UUID,
    seat_id: UUID,
    holder_name: str,
    holder_email: str | None = None,
    supporter_id: UUID | None = None,
    order_id: UUID | None = None,
) -> SeasonPass:
    """Sell a season ticket: one seat, every included match, separate tickets.

    Reserves the same physical seat across all of them and refuses the whole
    sale if any single match cannot give it up. A pass that covers nineteen of
    twenty matches is not a season ticket, and discovering the gap in February
    is worse than refusing it in July.
    """
    product = await session.scalar(
        select(SeasonTicketProduct).where(
            SeasonTicketProduct.tenant_id == tenant_id, SeasonTicketProduct.id == product_id
        )
    )
    if product is None:
        raise NotFound("That season ticket does not exist.")
    if product.status != "ON_SALE":
        raise Conflict("That season ticket is not on sale.")

    event_ids = list(
        await session.scalars(
            select(SeasonTicketEvent.event_id).where(
                SeasonTicketEvent.tenant_id == tenant_id,
                SeasonTicketEvent.product_id == product_id,
            )
        )
    )
    if not event_ids:
        raise ValidationFailed(
            "That season ticket does not include any matches yet.", field="product_id"
        )

    # Lock every match's row for this seat at once, in a deterministic order,
    # so two people buying the same seat serialise rather than interleave.
    rows = list(
        await session.scalars(
            select(EventSeatInventory)
            .where(
                EventSeatInventory.tenant_id == tenant_id,
                EventSeatInventory.seat_id == seat_id,
                EventSeatInventory.event_id.in_(event_ids),
            )
            .order_by(EventSeatInventory.id)
            .with_for_update()
        )
    )
    missing = set(event_ids) - {row.event_id for row in rows}
    if missing:
        raise ValidationFailed(
            "That seat does not exist in every match this season ticket covers.",
            field="seat_id",
            matches=len(missing),
        )

    from app.ticketing.inventory import is_free

    now = datetime.now(UTC)
    taken = [row for row in rows if not is_free(row, now=now)]
    if taken:
        raise SeatUnavailable(
            "That seat is not free for every match in this season ticket.",
            matches=len(taken),
        )

    first = rows[0]
    season_pass = SeasonPass(
        tenant_id=tenant_id,
        product_id=product_id,
        seat_id=seat_id,
        reference=_reference(),
        status="ACTIVE",
        holder_name=holder_name,
        holder_email=holder_email,
        supporter_id=supporter_id,
        order_id=order_id,
        price_paid_minor=product.price_minor,
        stand_name=first.stand_name,
        section_name=first.section_name,
        row_label=first.row_label,
        seat_label=first.seat_label,
    )
    session.add(season_pass)
    await session.flush()

    for row in rows:
        row.state = "SOLD"
        row.order_id = order_id
        row.hold_expires_at = None
        row.cart_id = None
        row.ticket_type_code = row.ticket_type_code or "ADULT"

        event = await session.scalar(
            select(TicketedEvent).where(
                TicketedEvent.tenant_id == tenant_id, TicketedEvent.id == row.event_id
            )
        )

        entitlement = EventEntitlement(
            tenant_id=tenant_id,
            event_id=row.event_id,
            inventory_id=row.id,
            source="SEASON_PASS",
            status="ACTIVE",
            season_pass_id=season_pass.id,
            order_id=order_id,
            ticket_type_code="SEASON",
            holder_name=holder_name,
            supporter_id=supporter_id,
        )
        session.add(entitlement)
        await session.flush()

        ticket = Ticket(
            tenant_id=tenant_id,
            event_id=row.event_id,
            entitlement_id=entitlement.id,
            ticket_number=_ticket_number("S"),
            status="ISSUED",
            ticket_type_code="SEASON",
            ticket_type_name="Season ticket",
            currency=product.currency,
            # Paid once, up front. Attributing a share of the season price to
            # each match would be an accounting choice this module has no
            # business making on the club's behalf.
            price_minor=0,
            order_id=order_id,
            season_pass_id=season_pass.id,
            holder_name=holder_name,
            issued_at=now,
        )
        session.add(ticket)
        await session.flush()

        await credential_service.mint(
            session,
            tenant_id,
            ticket=ticket,
            event_id=row.event_id,
            section_code=row.section_code,
            gate_codes=await _gate_codes_for_section(
                session, tenant_id, row.event_id, row.section_id
            ),
            valid_from=event.doors_open_at if event else None,
        )

    await session.flush()
    return season_pass


async def release_match(
    session: AsyncSession, tenant_id: UUID, *, entitlement_id: UUID
) -> EventEntitlement:
    """Hand one match of a season pass back to the club.

    The seat returns to public sale, the QR for that match dies, and the pass
    itself is untouched. This is the operation the per-match entitlement model
    exists to make possible.
    """
    entitlement = await session.scalar(
        select(EventEntitlement).where(
            EventEntitlement.tenant_id == tenant_id, EventEntitlement.id == entitlement_id
        )
    )
    if entitlement is None:
        raise NotFound("That entitlement does not exist.")
    if entitlement.source != "SEASON_PASS":
        raise ValidationFailed(
            "Only a season-ticket match can be released.", field="entitlement_id"
        )
    if entitlement.status != "ACTIVE":
        raise Conflict("That match has already been released or cancelled.")

    ticket = await session.scalar(
        select(Ticket).where(
            Ticket.tenant_id == tenant_id, Ticket.entitlement_id == entitlement_id
        )
    )
    if ticket is not None:
        await credential_service.revoke_active(session, tenant_id, ticket_id=ticket.id)
        ticket.status = "VOID"

    row = await session.scalar(
        select(EventSeatInventory).where(
            EventSeatInventory.tenant_id == tenant_id,
            EventSeatInventory.id == entitlement.inventory_id,
        )
    )
    if row is not None:
        row.state = "AVAILABLE"
        row.order_id = None
        row.cart_id = None

    entitlement.status = "RELEASED"
    entitlement.released_at = datetime.now(UTC)
    await session.flush()
    return entitlement


async def ticket_count_for_event(session: AsyncSession, tenant_id: UUID, event_id: UUID) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(Ticket)
            .where(
                Ticket.tenant_id == tenant_id,
                Ticket.event_id == event_id,
                Ticket.status == "ISSUED",
            )
        )
        or 0
    )
