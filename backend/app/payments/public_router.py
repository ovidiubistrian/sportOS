"""Where the buyer lands after paying.

BT iPay has no webhook. This handler is the only moment a shop order normally
learns its own outcome, and reconciliation is the only other one.

Two things it deliberately does not do.

It does not believe the redirect. A buyer arriving here proves they arrived;
whether any money moved is a question only the gateway can answer, and it is
asked before anything is written or shown.

It does not take the tenant from the host or a cookie. The buyer is coming from
the bank, carrying neither — the tenant is in the path, put there when the
return URL was built, which is the only part of this request we minted
ourselves.
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.core.db import tenant_session
from app.ordering.models import Order
from app.ordering.payments import settle
from app.payments.base import PaymentProviderError
from app.payments.models import PaymentAttempt
from app.payments.registry import build_provider
from app.tenants.models import ClubDomain

log = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])


async def _shop_url(session, club_id: UUID | None, outcome: str, reference: str | None) -> str:
    """The club's own shop page, saying what happened.

    Resolved from the club rather than from the request: the buyer arrives from
    the bank with no `Host` of ours to trust, and sending them to a domain
    derived from anything in this request would be a redirect an attacker gets
    to choose.
    """
    host = None
    if club_id is not None:
        host = await session.scalar(
            select(ClubDomain.hostname).where(
                ClubDomain.club_id == club_id,
                ClubDomain.verification_status == "VERIFIED",
            )
        )
    query = f"?payment={outcome}" + (f"&order={reference}" if reference else "")
    if not host:
        # Nothing to send them to. Rare enough to be a real fault, and better
        # as a page that says so than as a redirect to nowhere.
        return f"/shop{query}"
    return f"https://{host}/shop{query}"


@router.get("/return/{tenant_id}", include_in_schema=False)
async def payment_return(
    tenant_id: UUID,
    # The gateway's own spelling on the wire, ours in the code.
    order_id: Annotated[str | None, Query(alias="orderId")] = None,
    approval_code: Annotated[str | None, Query(alias="approvalCode")] = None,
) -> RedirectResponse:
    """Ask the gateway what happened, record it, and send the buyer onward.

    `approval_code` is the safety net. BT puts it in the return URL once a
    charge has been approved, so if the status call then fails — a slow
    sandbox, a dropped connection — there is independent evidence that money
    moved. Telling the buyer their payment failed at that point would be a lie
    about their own bank statement, so they are told it is being checked and
    reconciliation settles it within minutes.
    """
    async with tenant_session(tenant_id) as session:
        if not order_id:
            return RedirectResponse(
                await _shop_url(session, None, "unknown", None), status_code=303
            )

        attempt = await session.scalar(
            select(PaymentAttempt).where(
                PaymentAttempt.tenant_id == tenant_id,
                PaymentAttempt.session_id == order_id,
            )
        )
        if attempt is None:
            log.warning("Payment return for an unknown session: %s", order_id)
            return RedirectResponse(
                await _shop_url(session, None, "unknown", None), status_code=303
            )

        order = await session.scalar(
            select(Order).where(Order.tenant_id == tenant_id, Order.id == attempt.order_id)
        )
        club_id = order.club_id if order else None
        reference = order.reference if order else None

        provider = await build_provider(
            session, tenant_id, attempt.provider, order_ref=order_id
        )
        if provider is None:
            return RedirectResponse(
                await _shop_url(session, club_id, "pending", reference), status_code=303
            )

        try:
            status = await provider.get_session_status(order_id)
        except PaymentProviderError as exc:
            log.warning("Payment return could not reach the gateway for %s: %s", order_id, exc)
            outcome = "checking" if approval_code else "pending"
            return RedirectResponse(
                await _shop_url(session, club_id, outcome, reference), status_code=303
            )

        settled_order, just_paid = await settle(session, tenant_id, order_id, status)
        if settled_order is not None:
            reference = settled_order.reference
            club_id = settled_order.club_id

        if status.status in ("completed", "approved"):
            outcome = "success"
        elif status.status in ("failed", "expired"):
            outcome = "failed"
        else:
            outcome = "pending"

        if just_paid:
            log.info("Order %s paid by card", reference)

        target = await _shop_url(session, club_id, outcome, reference)

    return RedirectResponse(target, status_code=303)
