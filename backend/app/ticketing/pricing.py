"""What a ticket costs, and how that number is arrived at.

Prices live in a matrix of **price zone x ticket type**, held in a `PriceList`
that applies at one of three levels. Resolution walks them narrowest-first:

    EVENT  →  SEASON  →  VENUE

and takes the first rule it finds. A club sets its ground's prices once, adjusts
them for a season, and overrides a single derby — without ever restating the
rows it did not change. That is the whole reason for three levels rather than a
price column on the match: the alternative is copying eleven numbers onto every
fixture and getting one of them wrong in April.

VAT is kept as a rate in basis points plus an `is_included` flag, never as a
precomputed net and gross. Clubs disagree about which figure is "the price" —
some quote VAT-inclusive to supporters, some add it at checkout — and storing
only the derived pair loses the answer to which one the club actually chose.

Every amount is an integer in minor units, through `Money`. There are no floats
anywhere in this module, deliberately: a rounding error here is a discrepancy
somebody has to reconcile against a bank statement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, ValidationFailed
from app.core.money import Money
from app.ticketing.event_models import (
    PriceList,
    PriceRule,
    PromoCode,
    TicketedEvent,
    TicketType,
)

# Narrowest wins. The order is the policy, so it is stated once here rather
# than implied by the order of three queries.
SCOPE_PRECEDENCE = ("EVENT", "SEASON", "VENUE")


@dataclass(frozen=True, slots=True)
class TicketPrice:
    """One resolved cell of the matrix, with the fee that rides on it."""

    zone_code: str
    ticket_type_code: str
    ticket_type_name: str
    amount: Money
    vat_rate_bp: int
    vat_included: bool
    fee: Money

    @property
    def vat(self) -> Money:
        """The VAT component of `amount`, however the club quotes it.

        Inclusive: the tax already inside the price, which is
        `amount x rate / (1 + rate)` — not `amount x rate`, the mistake that
        overstates VAT on every inclusive line.
        """
        if not self.vat_rate_bp:
            return Money.zero(self.amount.currency)
        if self.vat_included:
            return Money(
                round(
                    self.amount.amount_minor * self.vat_rate_bp / (10_000 + self.vat_rate_bp)
                ),
                self.amount.currency,
            )
        return self.amount.percentage(self.vat_rate_bp)

    @property
    def total(self) -> Money:
        """What the supporter pays for this ticket, fee included."""
        gross = self.amount if self.vat_included else self.amount + self.vat
        return gross + self.fee


async def _price_lists(
    session: AsyncSession, tenant_id: UUID, event: TicketedEvent
) -> list[PriceList]:
    """Every list that could apply, narrowest first."""
    conditions = [PriceList.event_id == event.id]
    if event.season_id is not None:
        conditions.append(PriceList.season_id == event.season_id)
    conditions.append(PriceList.venue_id == event.venue_id)

    found = list(
        await session.scalars(
            select(PriceList).where(
                PriceList.tenant_id == tenant_id,
                # A season list anchored to a different venue must not leak in.
                (PriceList.event_id == event.id)
                | (
                    (PriceList.scope == "SEASON")
                    & (PriceList.season_id == event.season_id)
                    & (event.season_id is not None)
                )
                | ((PriceList.scope == "VENUE") & (PriceList.venue_id == event.venue_id)),
            )
        )
    )
    order = {scope: index for index, scope in enumerate(SCOPE_PRECEDENCE)}
    return sorted(found, key=lambda lst: order.get(lst.scope, 99))


async def resolve(
    session: AsyncSession,
    tenant_id: UUID,
    event: TicketedEvent,
    *,
    zone_code: str,
    ticket_type_code: str,
) -> TicketPrice:
    """The price for one zone and one ticket type, or a refusal.

    Refusing is correct behaviour, not a gap. A club that has not priced the
    away end has not decided what the away end costs, and inventing a number —
    or falling back to zero — would sell tickets at a price nobody approved.
    """
    ticket_type = await session.scalar(
        select(TicketType).where(
            TicketType.tenant_id == tenant_id, TicketType.code == ticket_type_code
        )
    )
    if ticket_type is None:
        raise NotFound(f"There is no ticket type called {ticket_type_code!r}.")

    for price_list in await _price_lists(session, tenant_id, event):
        rule = await session.scalar(
            select(PriceRule).where(
                PriceRule.tenant_id == tenant_id,
                PriceRule.price_list_id == price_list.id,
                PriceRule.price_zone_code == zone_code,
                PriceRule.ticket_type_id == ticket_type.id,
            )
        )
        if rule is None:
            continue

        currency = price_list.currency or event.currency
        return TicketPrice(
            zone_code=zone_code,
            ticket_type_code=ticket_type.code,
            ticket_type_name=ticket_type.name,
            amount=Money(rule.amount_minor, currency),
            vat_rate_bp=rule.vat_rate_bp,
            vat_included=rule.vat_included,
            # The event's per-ticket fee applies on top of any the rule
            # carries, so a club can charge a booking fee once centrally and
            # still add a surcharge for one match.
            fee=Money(rule.fee_minor + event.fee_per_ticket_minor, currency),
        )

    raise ValidationFailed(
        f"No price is set for {ticket_type.name} in zone {zone_code}.",
        field="pricing",
        zone=zone_code,
        ticket_type=ticket_type_code,
    )


async def priced_zone_codes(
    session: AsyncSession, tenant_id: UUID, event: TicketedEvent
) -> set[str]:
    """Which zones have at least one price. Used by the publish check."""
    codes: set[str] = set()
    for price_list in await _price_lists(session, tenant_id, event):
        codes.update(
            await session.scalars(
                select(PriceRule.price_zone_code)
                .where(
                    PriceRule.tenant_id == tenant_id,
                    PriceRule.price_list_id == price_list.id,
                )
                .distinct()
            )
        )
    return codes


async def matrix(
    session: AsyncSession, tenant_id: UUID, event: TicketedEvent, *, zone_codes: list[str]
) -> dict:
    """The whole grid, with each cell saying where its number came from.

    The provenance is what makes the screen usable: an administrator looking at
    a match needs to see at a glance which prices are this match's own and
    which are inherited from the season or the ground, because overriding one
    by accident is how a derby ends up at friendly prices.
    """
    types = list(
        await session.scalars(
            select(TicketType)
            .where(TicketType.tenant_id == tenant_id, TicketType.is_active.is_(True))
            .order_by(TicketType.display_order, TicketType.name)
        )
    )
    lists = await _price_lists(session, tenant_id, event)

    cells: list[dict] = []
    for zone_code in zone_codes:
        for ticket_type in types:
            resolved: dict | None = None
            for price_list in lists:
                rule = await session.scalar(
                    select(PriceRule).where(
                        PriceRule.tenant_id == tenant_id,
                        PriceRule.price_list_id == price_list.id,
                        PriceRule.price_zone_code == zone_code,
                        PriceRule.ticket_type_id == ticket_type.id,
                    )
                )
                if rule is not None:
                    resolved = {
                        "amount_minor": rule.amount_minor,
                        "vat_rate_bp": rule.vat_rate_bp,
                        "vat_included": rule.vat_included,
                        "fee_minor": rule.fee_minor,
                        "source": price_list.scope,
                        "price_list_id": str(price_list.id),
                        "rule_id": str(rule.id),
                    }
                    break
            cells.append(
                {
                    "zone_code": zone_code,
                    "ticket_type_id": str(ticket_type.id),
                    "ticket_type_code": ticket_type.code,
                    "ticket_type_name": ticket_type.name,
                    **(resolved or {"amount_minor": None, "source": None}),
                }
            )

    return {
        "currency": event.currency,
        "ticket_types": [
            {
                "id": str(t.id),
                "code": t.code,
                "name": t.name,
                "is_complimentary": t.is_complimentary,
            }
            for t in types
        ],
        "zone_codes": zone_codes,
        "cells": cells,
    }


async def apply_promo(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    code: str,
    event_id: UUID,
    subtotal: Money,
) -> tuple[Money, PromoCode]:
    """Resolve a promo code to a discount, or explain why it does not apply.

    Returns the discount, never a negative total: a fixed-amount code worth
    more than the basket discounts the basket to zero rather than owing the
    supporter money.
    """
    promo = await session.scalar(
        select(PromoCode).where(
            PromoCode.tenant_id == tenant_id, PromoCode.code == code.upper()
        )
    )
    if promo is None or not promo.is_active:
        raise ValidationFailed("That promotional code is not valid.", field="promo_code")

    now = datetime.now(UTC)
    if promo.starts_at and promo.starts_at > now:
        raise ValidationFailed("That code is not active yet.", field="promo_code")
    if promo.ends_at and promo.ends_at <= now:
        raise ValidationFailed("That code has expired.", field="promo_code")
    if promo.event_id is not None and promo.event_id != event_id:
        raise ValidationFailed("That code does not apply to this match.", field="promo_code")
    if promo.max_redemptions is not None and promo.redemption_count >= promo.max_redemptions:
        raise ValidationFailed("That code has been fully redeemed.", field="promo_code")

    if promo.discount_kind == "PERCENTAGE":
        discount = subtotal.percentage(promo.discount_value * 100)
    else:
        discount = Money(promo.discount_value, subtotal.currency)

    # Never more than the basket: a fixed-amount code worth more than what is
    # being bought discounts to zero rather than owing the supporter money.
    return discount.clamp(maximum=subtotal), promo
