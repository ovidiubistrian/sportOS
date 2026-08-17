"""Carts and checkout.

Checkout is deliberately one method. The ADR's five steps — reserve, price, pay,
fulfil, release — collapse to three here because Gate 1 takes payment at the
counter: there is nothing to reserve against a card that has not been charged,
and nothing to release when a supporter changes their mind. What is kept is the
*shape*: every line is priced through its handler before anything is written,
and every line is fulfilled through its handler afterwards, inside one
transaction. Adding tickets at Gate 2 adds a handler and a payment step, not a
second checkout.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, ValidationFailed
from app.core.money import Money
from app.ordering.handlers import LineRequest, handler_for
from app.ordering.models import Cart, CartLine, Order, OrderLine

log = structlog.get_logger(__name__)

CART_TTL = timedelta(days=14)

# Unambiguous when read aloud at a counter: no O/0, no I/1.
REFERENCE_ALPHABET = "ACDEFGHJKLMNPQRTUVWXY3456789"
MAX_LINES = 20
MAX_QUANTITY = 20


def new_cart_token() -> str:
    return secrets.token_urlsafe(24)


def new_reference() -> str:
    return "".join(secrets.choice(REFERENCE_ALPHABET) for _ in range(8))


class OrderingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- cart -------------------------------------------------------------

    async def get_cart(self, token: str, club_id: UUID) -> Cart | None:
        cart = await self.session.scalar(
            select(Cart).where(
                Cart.token == token, Cart.club_id == club_id, Cart.status == "OPEN"
            )
        )
        if cart is None:
            return None
        if cart.expires_at <= datetime.now(UTC):
            # Expired rather than deleted: a cart the supporter comes back to
            # after a fortnight should be empty, not a 404 they have to think
            # about.
            cart.status = "ABANDONED"
            return None
        return cart

    async def open_cart(self, tenant_id: UUID, club_id: UUID, currency: str) -> Cart:
        cart = Cart(
            tenant_id=tenant_id,
            club_id=club_id,
            token=new_cart_token(),
            status="OPEN",
            currency=currency,
            expires_at=datetime.now(UTC) + CART_TTL,
        )
        self.session.add(cart)
        await self.session.flush()
        return cart

    async def lines_of(self, cart: Cart) -> list[CartLine]:
        return list(
            await self.session.scalars(
                select(CartLine)
                .where(CartLine.cart_id == cart.id)
                .order_by(CartLine.created_at)
            )
        )

    async def set_line(
        self, cart: Cart, line_type: str, reference_id: UUID, quantity: int
    ) -> None:
        """Put a quantity in the basket. Zero removes the line.

        Set rather than add, so a double-tapped button cannot silently order two
        scarves — the client sends what the basket should contain, not a delta.
        """
        if quantity < 0 or quantity > MAX_QUANTITY:
            raise ValidationFailed(f"Choose between 1 and {MAX_QUANTITY}.", field="quantity")

        existing = await self.session.scalar(
            select(CartLine).where(
                CartLine.cart_id == cart.id,
                CartLine.line_type == line_type,
                CartLine.reference_id == reference_id,
            )
        )

        if quantity == 0:
            if existing is not None:
                await self.session.delete(existing)
                # Sessions here run with autoflush off, so without this the
                # basket read a line later still sees the row.
                await self.session.flush()
            return

        # Priced now purely to refuse the line early — a basket that accepts a
        # sold-out item and only complains at checkout wastes the buyer's time.
        handler = handler_for(line_type)
        await handler.price(
            self.session,
            LineRequest(line_type, reference_id, quantity),
            club_id=cart.club_id,
        )

        if existing is not None:
            existing.quantity = quantity
        else:
            if len(await self.lines_of(cart)) >= MAX_LINES:
                raise ValidationFailed(
                    f"A basket holds at most {MAX_LINES} different items.",
                    field="line_type",
                )
            self.session.add(
                CartLine(
                    tenant_id=cart.tenant_id,
                    cart_id=cart.id,
                    line_type=line_type,
                    reference_id=reference_id,
                    quantity=quantity,
                )
            )
        await self.session.flush()

    # --- checkout ---------------------------------------------------------

    async def checkout(
        self,
        cart: Cart,
        *,
        buyer_name: str,
        buyer_email: str | None,
        buyer_phone: str | None,
        note: str | None,
        supporter_id: UUID | None = None,
        payment_method: str = "ON_COLLECTION",
    ) -> Order:
        """Turn a basket into an order.

        One transaction. Every line is priced through its handler, the order is
        written from those prices rather than from anything the client sent, and
        every line is then fulfilled. A handler refusing at fulfilment — the last
        one sold while the form was open — rolls the whole thing back, which is
        the right answer while payment happens at the counter: nobody has been
        charged, so nobody has to be refunded.

        A card order takes its stock here too, and waits in `AWAITING_PAYMENT`
        until the bank says what happened. Holding nothing until the money
        lands would sell the last shirt to two people who both then pay for it,
        and one of them would have to be refunded and apologised to. An
        abandoned checkout instead holds a shirt until reconciliation gives up
        on it and returns the stock the way a cancellation does.
        """
        lines = await self.lines_of(cart)
        if not lines:
            raise ValidationFailed("Your basket is empty.", field="cart")

        requests = [
            LineRequest(line.line_type, line.reference_id, line.quantity) for line in lines
        ]
        priced = [
            await handler_for(request.line_type).price(
                self.session, request, club_id=cart.club_id
            )
            for request in requests
        ]

        subtotal = Money.zero(cart.currency)
        for line in priced:
            subtotal += line.total

        order = Order(
            tenant_id=cart.tenant_id,
            club_id=cart.club_id,
            reference=new_reference(),
            status=("AWAITING_PAYMENT" if payment_method == "CARD" else "AWAITING_COLLECTION"),
            currency=cart.currency,
            subtotal_minor=subtotal.amount_minor,
            total_minor=subtotal.amount_minor,
            buyer_name=buyer_name.strip(),
            buyer_email=buyer_email,
            buyer_phone=buyer_phone,
            note=note,
            supporter_id=supporter_id,
            payment_method=payment_method,
            placed_at=datetime.now(UTC),
        )
        self.session.add(order)
        await self.session.flush()

        for request, line in zip(requests, priced, strict=True):
            self.session.add(
                OrderLine(
                    tenant_id=cart.tenant_id,
                    order_id=order.id,
                    line_type=request.line_type,
                    reference_id=request.reference_id,
                    description=line.description,
                    unit_price_minor=line.unit_price.amount_minor,
                    quantity=line.quantity,
                    total_minor=line.total.amount_minor,
                )
            )

        for request in requests:
            await handler_for(request.line_type).fulfil(
                self.session, request, club_id=cart.club_id
            )

        cart.status = "CONVERTED"
        await self.session.flush()

        log.info(
            "order_placed",
            order_id=str(order.id),
            reference=order.reference,
            lines=len(requests),
            total_minor=order.total_minor,
        )
        return order

    async def cancel(self, order: Order) -> None:
        """Cancel an order and put everything back on the shelf."""
        if order.status == "COLLECTED":
            raise ValidationFailed("This order has already been collected.", field="status")
        if order.status == "CANCELLED":
            return

        for line in await self.session.scalars(
            select(OrderLine).where(OrderLine.order_id == order.id)
        ):
            await handler_for(line.line_type).reverse(
                self.session,
                LineRequest(line.line_type, line.reference_id, line.quantity),
                club_id=order.club_id,
            )
        order.status = "CANCELLED"
        await self.session.flush()

    async def collect(self, order: Order) -> None:
        if order.status == "CANCELLED":
            raise ValidationFailed("This order was cancelled.", field="status")
        order.status = "COLLECTED"
        order.collected_at = datetime.now(UTC)
        await self.session.flush()

    async def get_order(self, order_id: UUID, club_id: UUID) -> Order:
        order = await self.session.scalar(
            select(Order).where(Order.id == order_id, Order.club_id == club_id)
        )
        if order is None:
            raise NotFound(object_type="order", object_id=str(order_id))
        return order
