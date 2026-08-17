"""Which gateway a tenant uses, and whether it can take money at all.

The one place that turns stored settings into a working provider. Callers ask
for a tenant's provider and get either something usable or nothing — never a
half-built object that fails later, in front of a supporter.

`can_take_card` is the single answer to "should the shop offer to take a card",
and the public site asks exactly this. A club that has not finished setting up
is not shown a payment method that will refuse it.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.payments.base import PaymentProvider, PaymentProviderError
from app.payments.btipay import BtIpayProvider
from app.payments.journal import PaymentJournal
from app.payments.models import PaymentCredential

log = logging.getLogger(__name__)


def _setting(settings: dict, *names: str) -> str:
    """First of several spellings, stripped.

    Settings are written by one screen and read here, and the two have
    disagreed before: a form posting `userName` against a reader expecting
    `user_name` leaves a tenant configured everywhere except where it counts,
    with no error anywhere. Accepting both spellings costs nothing and removes
    a class of ghost.
    """
    for name in names:
        value = settings.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _btipay_ready(settings: dict) -> bool:
    return bool(_setting(settings, "user_name", "userName") and _setting(settings, "password"))


_READY = {"btipay": _btipay_ready}


async def _credentials(db: AsyncSession, tenant_id: UUID) -> list[PaymentCredential]:
    return list(
        await db.scalars(
            select(PaymentCredential).where(PaymentCredential.tenant_id == tenant_id)
        )
    )


async def configured_providers(db: AsyncSession, tenant_id: UUID) -> list[str]:
    """Providers this tenant could actually take a payment with, right now.

    Complete credentials and switched live. A club that has pasted a user name
    and stopped halfway is not on this list, and neither is one still testing.
    """
    out: list[str] = []
    for row in await _credentials(db, tenant_id):
        ready = _READY.get(row.provider)
        if ready and row.is_live and ready(row.settings or {}):
            out.append(row.provider)
    return out


async def can_take_card(db: AsyncSession, tenant_id: UUID) -> bool:
    """What the shop asks before offering a card at all."""
    return bool(await configured_providers(db, tenant_id))


async def build_provider(
    db: AsyncSession,
    tenant_id: UUID,
    provider: str,
    *,
    order_ref: str | None = None,
    require_live: bool = True,
) -> PaymentProvider | None:
    """Construct a tenant's provider, journal attached.

    `None` when the tenant has not configured it, so a checkout can answer
    "that payment method is not available here" instead of failing. The
    settings screen passes `require_live=False` to test credentials that have
    not been switched on yet.
    """
    key = (provider or "").strip().lower()
    row = await db.scalar(
        select(PaymentCredential).where(
            PaymentCredential.tenant_id == tenant_id,
            PaymentCredential.provider == key,
        )
    )
    if row is None:
        return None
    if require_live and not row.is_live:
        log.info("Tenant %s has %s configured but not live", tenant_id, key)
        return None

    settings = row.settings or {}
    journal = PaymentJournal(tenant_id, order_ref)
    try:
        if key == "btipay":
            return BtIpayProvider(
                user_name=_setting(settings, "user_name", "userName"),
                password=_setting(settings, "password"),
                # Sandbox unless told otherwise. The wrong way round would put
                # a club's first real sale through a test gateway.
                sandbox=bool(settings.get("sandbox", True)),
                child_id=_setting(settings, "child_id", "childId") or None,
            ).with_journal(journal)
    except PaymentProviderError as exc:
        log.warning("Tenant %s cannot use %s: %s", tenant_id, key, exc)
        return None

    log.warning("Unknown payment provider requested: %r", provider)
    return None
