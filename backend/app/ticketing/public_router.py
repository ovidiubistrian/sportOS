"""What a supporter uses: the seat map, the ten-minute hold, and checkout.

Host-scoped and unauthenticated, like the rest of the public API — buying a
ticket must not require an account.

**What this deliberately does not return.** The seat map tells a supporter that
a seat is free or not free, and never why. A seat held for a sponsor, blocked
for a camera platform or sitting in somebody else's basket all read the same:
unavailable. Publishing the difference would tell the internet which blocks a
club is holding back and how much of the ground is really sold, which is the
club's business and nobody else's.

**Checkout order.** Seats are confirmed under lock *before* the order is
placed, and tickets are issued after. The sequence matters: taking money for a
seat that expired thirty seconds ago is a refund and an apology, whereas
finding out first is a message asking the supporter to pick again.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.core.db import tenant_session
from app.core.errors import NotFound, ValidationFailed
from app.ordering.models import Cart, CartLine
from app.ordering.service import OrderingService
from app.payments.registry import can_take_card
from app.tenants.site_service import SiteRoute, resolve_host
from app.ticketing import inventory, issuing, pricing
from app.ticketing.event_models import EventSeatInventory, TicketedEvent
from app.ticketing.event_service import get_snapshot
from app.ticketing.ticket_models import AccessCredential, EventEntitlement, Ticket

router = APIRouter(prefix="/public/tickets", tags=["public-tickets"])

# Matches the hold. The countdown the supporter sees and the lifetime of the
# reservation are the same number by construction, not by two constants that
# drift apart.
HOLD_MINUTES = int(inventory.HOLD_TTL.total_seconds() // 60)


def _host(forwarded: str | None, header_host: str | None) -> str | None:
    return (forwarded or header_host or "").split(",")[0].strip() or None


async def _route_or_404(host: str | None) -> SiteRoute:
    route = await resolve_host(host) if host else None
    if route is None:
        raise NotFound("No club is published on this domain.")
    return route


class HoldIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inventory_ids: list[UUID] = Field(min_length=1, max_length=20)
    ticket_type_code: str = Field(default="ADULT", max_length=24)


class BestAvailableIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: int = Field(ge=1, le=20)
    section_id: UUID | None = None
    ticket_type_code: str = Field(default="ADULT", max_length=24)


class TicketCheckoutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=32)
    payment_method: Literal["ON_COLLECTION", "CARD"] = "ON_COLLECTION"
    promo_code: str | None = Field(default=None, max_length=32)
    note: str | None = None


async def _event_or_404(session, tenant_id: UUID, slug: str) -> TicketedEvent:
    event = await session.scalar(
        select(TicketedEvent).where(
            TicketedEvent.tenant_id == tenant_id, TicketedEvent.slug == slug
        )
    )
    if event is None or event.status != "PUBLISHED" or not event.is_public:
        raise NotFound("That match is not on sale.")
    return event


def _on_sale(event: TicketedEvent) -> None:
    now = datetime.now(UTC)
    if event.sales_start_at and now < event.sales_start_at:
        raise ValidationFailed("Tickets for this match are not on sale yet.", field="event")
    if event.sales_end_at and now > event.sales_end_at:
        raise ValidationFailed("Sales for this match have closed.", field="event")


@router.get("/events", summary="Matches on sale")
async def list_public_events(
    response: Response,
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    host: Annotated[str | None, Header(alias="Host")] = None,
) -> list[dict[str, Any]]:
    route = await _route_or_404(_host(x_forwarded_host, host))
    response.headers["Cache-Control"] = "public, max-age=60"

    async with tenant_session(route.tenant_id) as session:
        events = list(
            await session.scalars(
                select(TicketedEvent)
                .where(
                    TicketedEvent.tenant_id == route.tenant_id,
                    TicketedEvent.club_id == route.club_id,
                    TicketedEvent.status == "PUBLISHED",
                    TicketedEvent.is_public.is_(True),
                    TicketedEvent.kickoff_at >= datetime.now(UTC) - timedelta(hours=4),
                )
                .order_by(TicketedEvent.kickoff_at)
            )
        )
        out = []
        for event in events:
            summary = await inventory.availability_by_section(
                session, route.tenant_id, event.id
            )
            out.append(
                {
                    "slug": event.slug,
                    "name": event.name,
                    "opponent_name": event.opponent_name,
                    "competition_label": event.competition_label,
                    "kickoff_at": event.kickoff_at.isoformat(),
                    "doors_open_at": event.doors_open_at.isoformat()
                    if event.doors_open_at
                    else None,
                    "currency": event.currency,
                    "available": sum(row["available"] for row in summary),
                }
            )
        return out


@router.get("/events/{slug}", summary="The seat map for one match")
async def public_event(
    slug: str,
    response: Response,
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    host: Annotated[str | None, Header(alias="Host")] = None,
) -> dict[str, Any]:
    """The frozen layout plus a free/total count per sector.

    Counts, not seat states, at this level: the overview draws a whole stadium
    and does not need thirty thousand rows to colour twelve sectors.
    """
    route = await _route_or_404(_host(x_forwarded_host, host))
    response.headers["Cache-Control"] = "no-store"

    async with tenant_session(route.tenant_id) as session:
        event = await _event_or_404(session, route.tenant_id, slug)
        snapshot = await get_snapshot(session, route.tenant_id, event.id)
        availability = await inventory.availability_by_section(
            session, route.tenant_id, event.id
        )

        prices: dict[str, Any] = {}
        for row in availability:
            code = row["price_zone_code"]
            if not code or code in prices:
                continue
            try:
                resolved = await pricing.resolve(
                    session,
                    route.tenant_id,
                    event,
                    zone_code=code,
                    ticket_type_code="ADULT",
                )
            except (ValidationFailed, NotFound):
                # An unpriced zone is shown as unavailable rather than free.
                continue
            prices[code] = {
                "amount_minor": resolved.total.amount_minor,
                "currency": resolved.total.currency,
            }

        return {
            "slug": event.slug,
            "name": event.name,
            "kickoff_at": event.kickoff_at.isoformat(),
            "doors_open_at": event.doors_open_at.isoformat() if event.doors_open_at else None,
            "currency": event.currency,
            "max_per_customer": event.max_per_customer,
            "hold_minutes": HOLD_MINUTES,
            "layout": snapshot.payload,
            "availability": availability,
            "prices": prices,
        }


@router.get("/events/{slug}/seats", summary="Seats in one sector")
async def public_seats(
    slug: str,
    section_id: UUID,
    response: Response,
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    host: Annotated[str | None, Header(alias="Host")] = None,
) -> dict[str, Any]:
    """Seat-level detail, free or not and nothing more.

    `available` is a boolean on purpose. A supporter has no business knowing
    that row G is held for the press rather than simply taken.
    """
    route = await _route_or_404(_host(x_forwarded_host, host))
    response.headers["Cache-Control"] = "no-store"

    async with tenant_session(route.tenant_id) as session:
        event = await _event_or_404(session, route.tenant_id, slug)
        now = datetime.now(UTC)

        rows = list(
            await session.scalars(
                select(EventSeatInventory)
                .where(
                    EventSeatInventory.tenant_id == route.tenant_id,
                    EventSeatInventory.event_id == event.id,
                    EventSeatInventory.section_id == section_id,
                )
                .order_by(EventSeatInventory.row_label, EventSeatInventory.seat_index)
            )
        )
        if not rows:
            raise NotFound("That part of the ground is not part of this match.")

        return {
            "section_id": str(section_id),
            "kind": rows[0].section_kind,
            "seats": [
                {
                    "id": str(row.id),
                    "row": row.row_label,
                    "seat": row.seat_label,
                    "index": row.seat_index,
                    "kind": row.seat_kind,
                    "zone": row.price_zone_code,
                    "available": inventory.is_free(row, now=now),
                }
                for row in rows
            ],
        }


async def _cart_for(session, route: SiteRoute, token: str | None, currency: str) -> Cart:
    service = OrderingService(session)
    if token:
        cart = await service.get_cart(token, route.club_id)
        if cart is not None:
            return cart
    return await service.open_cart(route.tenant_id, route.club_id, currency)


def _hold_view(rows: list[EventSeatInventory], cart: Cart) -> dict[str, Any]:
    expires = max((r.hold_expires_at for r in rows if r.hold_expires_at), default=None)
    return {
        "cart_token": cart.token,
        "expires_at": expires.isoformat() if expires else None,
        "seconds_remaining": int((expires - datetime.now(UTC)).total_seconds())
        if expires
        else 0,
        "seats": [
            {
                "id": str(row.id),
                "stand": row.stand_name,
                "section": row.section_name,
                "row": row.row_label,
                "seat": row.seat_label,
                "zone": row.price_zone_code,
            }
            for row in rows
        ],
    }


@router.post("/events/{slug}/hold", summary="Hold seats for ten minutes")
async def hold_seats(
    slug: str,
    payload: HoldIn,
    response: Response,
    x_cart_token: Annotated[str | None, Header(alias="X-Cart-Token")] = None,
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    host: Annotated[str | None, Header(alias="Host")] = None,
) -> dict[str, Any]:
    route = await _route_or_404(_host(x_forwarded_host, host))
    response.headers["Cache-Control"] = "no-store"

    async with tenant_session(route.tenant_id) as session:
        event = await _event_or_404(session, route.tenant_id, slug)
        _on_sale(event)

        cart = await _cart_for(session, route, x_cart_token, event.currency)
        # Replace rather than add to: the seat picker sends the whole selection
        # each time, so a supporter deselecting a seat must give it back.
        await inventory.release_cart(session, route.tenant_id, cart.id)
        await session.execute(
            CartLine.__table__.delete().where(
                CartLine.tenant_id == route.tenant_id,
                CartLine.cart_id == cart.id,
                CartLine.line_type == "TICKET",
            )
        )

        rows = await inventory.hold(
            session,
            route.tenant_id,
            event_id=event.id,
            cart_id=cart.id,
            inventory_ids=payload.inventory_ids,
            ticket_type_code=payload.ticket_type_code,
        )
        for row in rows:
            session.add(
                CartLine(
                    tenant_id=route.tenant_id,
                    cart_id=cart.id,
                    line_type="TICKET",
                    reference_id=row.id,
                    quantity=1,
                )
            )
        await session.flush()
        return _hold_view(rows, cart)


@router.post("/events/{slug}/best-available", summary="Pick seats for me")
async def best_available(
    slug: str,
    payload: BestAvailableIn,
    response: Response,
    x_cart_token: Annotated[str | None, Header(alias="X-Cart-Token")] = None,
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    host: Annotated[str | None, Header(alias="Host")] = None,
) -> dict[str, Any]:
    route = await _route_or_404(_host(x_forwarded_host, host))
    response.headers["Cache-Control"] = "no-store"

    async with tenant_session(route.tenant_id) as session:
        event = await _event_or_404(session, route.tenant_id, slug)
        _on_sale(event)

        found = await inventory.best_available(
            session,
            route.tenant_id,
            event_id=event.id,
            quantity=payload.quantity,
            section_id=payload.section_id,
        )
        cart = await _cart_for(session, route, x_cart_token, event.currency)
        await inventory.release_cart(session, route.tenant_id, cart.id)
        await session.execute(
            CartLine.__table__.delete().where(
                CartLine.tenant_id == route.tenant_id,
                CartLine.cart_id == cart.id,
                CartLine.line_type == "TICKET",
            )
        )

        rows = await inventory.hold(
            session,
            route.tenant_id,
            event_id=event.id,
            cart_id=cart.id,
            inventory_ids=[row.id for row in found],
            ticket_type_code=payload.ticket_type_code,
        )
        for row in rows:
            session.add(
                CartLine(
                    tenant_id=route.tenant_id,
                    cart_id=cart.id,
                    line_type="TICKET",
                    reference_id=row.id,
                    quantity=1,
                )
            )
        await session.flush()
        return _hold_view(rows, cart)


@router.delete("/holds", status_code=204, summary="Give the seats back")
async def release_hold(
    x_cart_token: Annotated[str | None, Header(alias="X-Cart-Token")] = None,
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    host: Annotated[str | None, Header(alias="Host")] = None,
) -> None:
    route = await _route_or_404(_host(x_forwarded_host, host))
    if not x_cart_token:
        return

    async with tenant_session(route.tenant_id) as session:
        cart = await OrderingService(session).get_cart(x_cart_token, route.club_id)
        if cart is None:
            return
        await inventory.release_cart(session, route.tenant_id, cart.id)
        await session.execute(
            CartLine.__table__.delete().where(
                CartLine.tenant_id == route.tenant_id,
                CartLine.cart_id == cart.id,
                CartLine.line_type == "TICKET",
            )
        )


@router.post("/events/{slug}/checkout", summary="Buy the held seats")
async def checkout_tickets(
    slug: str,
    payload: TicketCheckoutIn,
    response: Response,
    x_cart_token: Annotated[str | None, Header(alias="X-Cart-Token")] = None,
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    host: Annotated[str | None, Header(alias="Host")] = None,
) -> dict[str, Any]:
    """Place the order, bind the seats to it, and issue the tickets.

    In that order and in one transaction. The ordering kernel prices and
    records the sale; the seats are then confirmed under lock — which is where
    an expired hold is caught — and only then does a ticket exist.

    The kernel's `fulfil` hook cannot do the binding itself: it is handed
    `(session, request, club_id)` and never the order, because most sellable
    things do not care which order they belong to. Tickets do, so the caller
    that has the order does the work. See `ordering_handlers`.
    """
    route = await _route_or_404(_host(x_forwarded_host, host))
    response.headers["Cache-Control"] = "no-store"

    if not x_cart_token:
        raise NotFound("Your reservation has expired.")

    async with tenant_session(route.tenant_id) as session:
        event = await _event_or_404(session, route.tenant_id, slug)
        _on_sale(event)

        service = OrderingService(session)
        cart = await service.get_cart(x_cart_token, route.club_id)
        if cart is None:
            raise NotFound("Your reservation has expired.")

        if payload.payment_method == "CARD" and not await can_take_card(
            session, route.tenant_id
        ):
            raise ValidationFailed(
                "This club is not taking card payments yet.", field="payment_method"
            )

        order = await service.checkout(
            cart,
            buyer_name=payload.name,
            buyer_email=payload.email,
            buyer_phone=payload.phone,
            note=payload.note,
            payment_method=payload.payment_method,
        )

        # Under lock, and after the money question is settled. A hold that
        # lapsed during checkout fails here, before a ticket exists.
        await inventory.confirm_sold(
            session,
            route.tenant_id,
            cart_id=cart.id,
            order_id=order.id,
            event_id=event.id,
        )
        tickets = await issuing.issue_for_order(
            session, route.tenant_id, order_id=order.id, holder_name=payload.name
        )

        return {
            "reference": order.reference,
            "status": order.status,
            "total_minor": order.total_minor,
            "currency": order.currency,
            "tickets": [
                {
                    "ticket_number": ticket.ticket_number,
                    "ticket_type": ticket.ticket_type_name,
                    "price_minor": ticket.price_minor,
                }
                for ticket in tickets
            ],
        }


@router.get("/orders/{reference}", summary="A placed order and its QR codes")
async def public_order(
    reference: str,
    response: Response,
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    host: Annotated[str | None, Header(alias="Host")] = None,
) -> dict[str, Any]:
    """The confirmation page, and where the QR codes are collected from.

    Guarded by the order reference, which is short and human — so it is
    generated unpredictably rather than sequentially, and the QR payload itself
    is separately random. Guessing a reference reveals one order; it does not
    reveal a pattern that yields the next.
    """
    from app.ordering.models import Order
    from app.ticketing.credentials import qr_payload

    route = await _route_or_404(_host(x_forwarded_host, host))
    response.headers["Cache-Control"] = "no-store"

    async with tenant_session(route.tenant_id) as session:
        order = await session.scalar(
            select(Order).where(
                Order.tenant_id == route.tenant_id,
                Order.club_id == route.club_id,
                Order.reference == reference,
            )
        )
        if order is None:
            raise NotFound("That order does not exist.")

        tickets = list(
            await session.scalars(
                select(Ticket).where(
                    Ticket.tenant_id == route.tenant_id, Ticket.order_id == order.id
                )
            )
        )
        out = []
        for ticket in tickets:
            credential = await session.scalar(
                select(AccessCredential).where(
                    AccessCredential.tenant_id == route.tenant_id,
                    AccessCredential.ticket_id == ticket.id,
                    AccessCredential.status == "ACTIVE",
                )
            )
            # Seat labels come from the event's own inventory, through the
            # entitlement — never from the master, which may have been redrawn
            # since this ticket was sold.
            entitlement = await session.scalar(
                select(EventEntitlement).where(
                    EventEntitlement.tenant_id == route.tenant_id,
                    EventEntitlement.id == ticket.entitlement_id,
                )
            )
            row = (
                await session.scalar(
                    select(EventSeatInventory).where(
                        EventSeatInventory.tenant_id == route.tenant_id,
                        EventSeatInventory.id == entitlement.inventory_id,
                    )
                )
                if entitlement
                else None
            )
            out.append(
                {
                    "ticket_number": ticket.ticket_number,
                    "ticket_type": ticket.ticket_type_name,
                    "holder_name": ticket.holder_name,
                    "price_minor": ticket.price_minor,
                    "currency": ticket.currency,
                    "stand": row.stand_name if row else None,
                    "section": row.section_name if row else None,
                    "row": row.row_label if row else None,
                    "seat": row.seat_label if row else None,
                    "gate": credential.gate_codes if credential else None,
                    "qr": qr_payload(credential) if credential else None,
                }
            )

        return {
            "reference": order.reference,
            "status": order.status,
            "total_minor": order.total_minor,
            "currency": order.currency,
            "buyer_name": order.buyer_name,
            "tickets": out,
        }
