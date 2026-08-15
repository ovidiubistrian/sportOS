"""The line-handler registry (ADR-0005 §Decision).

`ordering` knows how to price, place and fulfil an order. It does not know what
a ticket is, or a scarf. Each sellable domain registers a handler for its line
type, and checkout is the same five steps regardless of what is in the cart:

    reserve every line → price every line → take payment → fulfil every line

which is what makes a mixed cart — two tickets, a scarf and a donation, one
payment — work by construction rather than by a later rewrite.

`ordering` must not import the modules that register handlers; they import it.
That inverts the intuitive direction and the ADR says so: `ordering` is tier 2,
below the domains it serves. The registry is what lets the dependency point the
right way.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationFailed
from app.core.money import Money


@dataclass(frozen=True, slots=True)
class LineRequest:
    """What the buyer asked for, before anything has been checked."""

    line_type: str
    reference_id: UUID
    quantity: int


@dataclass(frozen=True, slots=True)
class PricedLine:
    """What it costs and what it is called, resolved at checkout.

    `description` is snapshotted onto the order line: it has to still read
    correctly after the club renames the product.
    """

    description: str
    unit_price: Money
    quantity: int

    @property
    def total(self) -> Money:
        return self.unit_price * self.quantity


class OrderLineHandler(Protocol):
    """Implemented by each sellable domain."""

    line_type: str

    async def price(
        self, session: AsyncSession, request: LineRequest, *, club_id: UUID
    ) -> PricedLine:
        """Resolve the line, or refuse it.

        Raises `ValidationFailed` if the thing is not for sale — sold out,
        withdrawn, or belonging to another club.
        """
        ...

    async def fulfil(
        self, session: AsyncSession, request: LineRequest, *, club_id: UUID
    ) -> None:
        """Make it true: decrement stock, mint a credential, activate a member."""
        ...

    async def reverse(
        self, session: AsyncSession, request: LineRequest, *, club_id: UUID
    ) -> None:
        """Undo a fulfilment — a cancelled order puts the stock back."""
        ...


_HANDLERS: dict[str, OrderLineHandler] = {}


def register(handler: OrderLineHandler) -> OrderLineHandler:
    """Register a handler for its line type.

    Called at import time by the owning module. Re-registration replaces, so a
    module reloaded in a test does not raise.
    """
    _HANDLERS[handler.line_type] = handler
    return handler


def handler_for(line_type: str) -> OrderLineHandler:
    handler = _HANDLERS.get(line_type)
    if handler is None:
        # The database constrains `line_type` to the catalogue, so this means a
        # type is in the catalogue with nothing implementing it — a deployment
        # mistake, not something a buyer did.
        raise ValidationFailed(
            f"Nothing on this platform sells {line_type.lower()}s yet.",
            field="line_type",
        )
    return handler


def registered_types() -> tuple[str, ...]:
    return tuple(sorted(_HANDLERS))
