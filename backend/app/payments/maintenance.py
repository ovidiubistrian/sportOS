"""Asking the bank about the buyers who never came back.

BT iPay has no webhook, so an order learns its outcome when the buyer returns
to the return URL — and a browser closed on the bank's confirmation screen
never returns. Without this the order would sit in `AWAITING_PAYMENT` forever,
holding stock, for a payment that may already have been taken.

It runs in the relay's maintenance loop rather than a cron on the host. That
loop is already deployed, already supervised, and already logs where everything
else does; a shell script calling an HTTP endpoint with a shared secret is one
more thing to install, rotate and forget.

Two jobs, and the order between them is the point.

`reconcile_card_payments` asks about orders old enough that the buyer is no
longer typing and young enough that the session still exists. That is where
a genuinely paid order gets confirmed.

`release_abandoned_orders` deals with what is left when the window has passed:
the stock a card order took at checkout has to go back, and this is the only
thing that returns it. It asks the bank one final time first, because giving up
on an order somebody paid for is the expensive mistake — and it refuses to give
up at all on an answer of "still in flight" or on no answer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy import select

from app.core.db import platform_session, tenant_session
from app.ordering.models import Order
from app.ordering.payments import ATTEMPT_TTL, reconcile_order
from app.ordering.service import OrderingService

log = structlog.get_logger(__name__)

# Long enough that a buyer still at a payment page is left alone.
SETTLE_AFTER = timedelta(minutes=3)

# One sweep's worth. Bounded so a backlog cannot turn a single run into a
# thousand calls to a bank.
BATCH_SIZE = 100


async def _orders_awaiting_payment(
    *, older_than: timedelta, younger_than: timedelta | None
) -> list[tuple[UUID, UUID]]:
    """Tenant and order ids only — the rows themselves are read per tenant.

    Cross-tenant, because the relay has no tenant of its own, and identifiers
    are all that may safely leave that scope.
    """
    now = datetime.now(UTC)
    clauses = [Order.status == "AWAITING_PAYMENT", Order.placed_at < now - older_than]
    if younger_than is not None:
        clauses.append(Order.placed_at > now - younger_than)

    async with platform_session(reason="find orders awaiting payment", routine=True) as session:
        rows = await session.execute(
            select(Order.tenant_id, Order.id)
            .where(*clauses)
            .order_by(Order.placed_at)
            .limit(BATCH_SIZE)
        )
        return [(row.tenant_id, row.id) for row in rows]


async def _for_each(pairs: list[tuple[UUID, UUID]], handle) -> dict[str, int]:
    """Run `handle(session, order)` per order, each in its own transaction.

    Tenant-bound, so reconciliation writes through the same row-level security
    every other write does — and so one club's bank being unreachable cannot
    roll back another club's payment.
    """
    tally: dict[str, int] = {}
    for tenant_id, order_id in pairs:
        try:
            async with tenant_session(tenant_id) as session:
                order = await session.scalar(
                    select(Order).where(Order.tenant_id == tenant_id, Order.id == order_id)
                )
                # Re-read under the tenant's own transaction: the return
                # handler may have settled this order since the sweep listed it.
                if order is None or order.status != "AWAITING_PAYMENT":
                    continue
                outcome = await handle(session, order)
        except Exception:
            log.exception("payment_maintenance_failed", order_id=str(order_id))
            outcome = "error"
        tally[outcome] = tally.get(outcome, 0) + 1
    return tally


async def reconcile_card_payments() -> dict[str, int]:
    """Confirm the orders the bank says were paid for."""
    pairs = await _orders_awaiting_payment(older_than=SETTLE_AFTER, younger_than=ATTEMPT_TTL)
    if not pairs:
        return {}

    tally = await _for_each(pairs, lambda session, order: reconcile_order(session, order))
    if tally.get("paid"):
        log.info("card_payments_reconciled", **tally)
    return tally


async def release_abandoned_orders() -> dict[str, int]:
    """Put back the stock of orders that were never paid for.

    The last word on an order, and deliberately cautious: the bank is asked
    once more, and anything other than a clear "nobody paid" leaves the order
    alone for the next sweep. An order cancelled out from under a completed
    payment is money taken for goods put back on the shelf, which is worse in
    every direction than a shirt held a few hours too long.
    """

    async def handle(session, order: Order) -> str:
        outcome = await reconcile_order(session, order)
        if outcome != "unpaid":
            # paid, in_progress, unreachable, no_provider — none of them is
            # permission to cancel.
            return outcome
        await OrderingService(session).cancel(order)
        log.info("abandoned_order_released", reference=order.reference)
        return "released"

    pairs = await _orders_awaiting_payment(older_than=ATTEMPT_TTL, younger_than=None)
    if not pairs:
        return {}

    tally = await _for_each(pairs, handle)
    if tally.get("released"):
        log.info("abandoned_orders_released", **tally)
    return tally
