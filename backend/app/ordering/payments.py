"""Paying for an order by card.

The seam between the shop and the payment port. This module knows what an order
is; `app/payments` knows what a gateway is; neither knows the other's business.

The shape of the flow, and why:

    checkout      the order is written and its stock is taken, exactly as it is
                  for payment at the counter, but the order rests in
                  AWAITING_PAYMENT and an attempt is registered with the gateway
    return        the buyer comes back and we ask the gateway what happened
    reconcile     for the buyer who never came back

Stock is taken before the money, not after. The alternative — hold nothing until
the payment lands — sells the last shirt twice to two people who both then pay
for it, and one of them has to be refunded and apologised to. Taking it up front
means an abandoned checkout holds a shirt until the attempt is given up on,
which reconciliation does, returning the stock through the same handler that
took it.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ordering.models import Order
from app.payments.base import CheckoutSession, PaymentProviderError, SessionStatus
from app.payments.btipay import LIVE_ORDER_STATUSES, PAID_ORDER_STATUS
from app.payments.models import PaymentAttempt
from app.payments.registry import build_provider

log = logging.getLogger(__name__)

# What the gateway echoes back to us. The prefix is what lets one return
# handler serve more than one kind of purchase later without guessing.
ORDER_REF_PREFIX = "so_"

# How long an attempt may stay unanswered before reconciliation stops asking.
# Comfortably longer than any authentication takes and shorter than the window
# in which a club would still want the stock back.
ATTEMPT_TTL = timedelta(hours=6)


def order_ref(order: Order) -> str:
    return f"{ORDER_REF_PREFIX}{order.id}"


def parse_order_ref(ref: str) -> UUID | None:
    if not ref or not ref.startswith(ORDER_REF_PREFIX):
        return None
    try:
        return UUID(ref[len(ORDER_REF_PREFIX) :])
    except ValueError:
        return None


async def start_card_payment(
    db: AsyncSession,
    order: Order,
    *,
    provider_key: str,
    return_url: str,
    club_name: str | None = None,
) -> CheckoutSession:
    """Register this order with the gateway and record the attempt.

    Everything the gateway needs about the buyer is passed here, from the order
    we already hold. The provider does not read the database: it is given what
    to send, which keeps it ignorant of orders and keeps this the only place
    that decides what a buyer's details are.
    """
    ref = order_ref(order)
    provider = await build_provider(db, order.tenant_id, provider_key, order_ref=ref)
    if provider is None:
        raise PaymentProviderError("This club cannot take card payments yet.")

    session = await provider.create_checkout_session(
        order_ref=ref,
        amount_minor=order.total_minor,
        currency=order.currency,
        return_url=return_url,
        buyer_email=order.buyer_email,
        metadata={
            "description": f"{club_name or 'Comanda'} {order.reference}",
            "phone": order.buyer_phone or "",
            # A shop order is collected at the counter, so there is no delivery
            # address and none is invented. The gateway accepts the omission
            # and refuses a placeholder.
        },
    )

    db.add(
        PaymentAttempt(
            tenant_id=order.tenant_id,
            order_id=order.id,
            provider=provider.key,
            session_id=session.session_id,
            amount_minor=order.total_minor,
            currency=order.currency,
            state="pending",
        )
    )
    await db.flush()
    log.info(
        "Card payment started: order=%s provider=%s session=%s",
        order.reference,
        provider.key,
        session.session_id,
    )
    return session


async def _attempt_for(
    db: AsyncSession, tenant_id: UUID, session_id: str
) -> PaymentAttempt | None:
    return await db.scalar(
        select(PaymentAttempt).where(
            PaymentAttempt.tenant_id == tenant_id,
            PaymentAttempt.session_id == session_id,
        )
    )


async def settle(
    db: AsyncSession,
    tenant_id: UUID,
    session_id: str,
    status: SessionStatus,
) -> tuple[Order | None, bool]:
    """Apply what the gateway said to the order behind this session.

    Returns the order and whether this call is the one that confirmed it —
    callers use that to send a receipt exactly once, however many times a buyer
    refreshes the page they landed on.

    Idempotent by construction: an order already collected or cancelled is left
    alone, and an attempt already settled is not settled twice.
    """
    attempt = await _attempt_for(db, tenant_id, session_id)
    if attempt is None:
        log.warning(
            "Payment for an unknown session: tenant=%s session=%s", tenant_id, session_id
        )
        return None, False

    order = await db.scalar(
        select(Order).where(Order.tenant_id == tenant_id, Order.id == attempt.order_id)
    )
    if order is None:
        return None, False

    attempt.state = status.status
    if status.status in ("completed", "approved"):
        # `approved` is a two-phase hold. The money is committed as far as the
        # buyer is concerned and the club captures it later, so the order is
        # theirs to collect either way.
        just_paid = order.status == "AWAITING_PAYMENT"
        if just_paid:
            order.status = "AWAITING_COLLECTION"
            order.payment_method = "CARD"
        attempt.settled_at = datetime.now(UTC)
        await db.flush()
        return order, just_paid

    if status.status in ("failed", "expired"):
        attempt.settled_at = datetime.now(UTC)
        await db.flush()
        return order, False

    # Still in flight. Deliberately not settled: the buyer may be on their
    # bank's screen, and this attempt must stay askable.
    await db.flush()
    return order, False


async def reconcile_order(db: AsyncSession, order: Order) -> str:
    """Ask the gateway about every attempt on this order, and act on the truth.

        paid          one attempt completed; the order is now collectable
        in_progress   an attempt is live — money held, or a buyer mid-authentication
        unpaid        every attempt is dead; the order may be given up on
        unreachable   the gateway could not be asked; decide nothing this round
        no_provider   the club has no gateway configured

    The distinction between `in_progress` and `unpaid` is the whole point, and
    it cannot be made from the provider-neutral word: a gateway reports "nobody
    has tried" and "the buyer is authenticating right now" as the same state to
    a caller reading only `SessionStatus.status`. The raw code is read here for
    that one decision, and nowhere else.
    """
    attempts = list(
        await db.scalars(
            select(PaymentAttempt)
            .where(
                PaymentAttempt.tenant_id == order.tenant_id,
                PaymentAttempt.order_id == order.id,
            )
            .order_by(PaymentAttempt.created_at.desc())
        )
    )
    if not attempts:
        return "unpaid"

    unreachable = False
    live = False
    for attempt in attempts:
        provider = await build_provider(
            db, order.tenant_id, attempt.provider, order_ref=order_ref(order)
        )
        if provider is None:
            return "no_provider"
        try:
            status = await provider.get_session_status(attempt.session_id)
        except PaymentProviderError as exc:
            unreachable = True
            log.warning(
                "Reconcile could not reach the gateway: order=%s session=%s: %s",
                order.reference,
                attempt.session_id,
                exc,
            )
            continue

        raw_code = _raw_order_status(status)
        if raw_code == PAID_ORDER_STATUS or status.status == "completed":
            await settle(db, order.tenant_id, attempt.session_id, status)
            log.info(
                "Reconcile confirmed order %s from session %s",
                order.reference,
                attempt.session_id,
            )
            return "paid"
        if raw_code in LIVE_ORDER_STATUSES or status.status == "approved":
            live = True
        else:
            attempt.state = status.status
            attempt.settled_at = datetime.now(UTC)

    await db.flush()
    if live:
        return "in_progress"
    if unreachable:
        return "unreachable"
    return "unpaid"


def _raw_order_status(status: SessionStatus) -> int:
    """The gateway's own code, for the one decision the mapped word cannot make."""
    try:
        return int((status.raw or {}).get("orderStatus"))
    except (TypeError, ValueError):
        return -1


async def orders_awaiting_payment(
    db: AsyncSession, *, older_than: timedelta, limit: int = 200
) -> list[Order]:
    """Orders that started a card payment and have not been heard about since.

    `older_than` keeps reconciliation off the back of a buyer who is still
    typing their card number; the ceiling keeps one sweep bounded.
    """
    cutoff = datetime.now(UTC) - older_than
    return list(
        await db.scalars(
            select(Order)
            .where(
                Order.status == "AWAITING_PAYMENT",
                Order.placed_at < cutoff,
                Order.placed_at > datetime.now(UTC) - ATTEMPT_TTL,
            )
            .order_by(Order.placed_at)
            .limit(limit)
        )
    )
