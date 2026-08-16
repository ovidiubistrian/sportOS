"""The PRODUCT line handler.

`commerce` imports `ordering`, never the other way round: the kernel is tier 2
and this is tier 3. Registering here is what lets the shop plug into a checkout
that knows nothing about scarves.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.commerce.models import Product, ProductVariant
from app.core.errors import ValidationFailed
from app.core.money import Money
from app.ordering.handlers import LineRequest, PricedLine, register


class ProductLineHandler:
    """A line of the club shop. `reference_id` is a variant, not a product."""

    line_type = "PRODUCT"

    async def _resolve(
        self, session: AsyncSession, reference_id: UUID, club_id: UUID
    ) -> tuple[Product, ProductVariant]:
        row = (
            await session.execute(
                select(ProductVariant, Product)
                .join(Product, Product.id == ProductVariant.product_id)
                .where(ProductVariant.id == reference_id, Product.club_id == club_id)
            )
        ).first()
        if row is None:
            # Withdrawn between browsing and checkout, or simply not this
            # club's. Either way the buyer needs a sentence, not a 500.
            raise ValidationFailed("That item is no longer in the shop.", field="reference_id")
        variant, product = row
        if not product.is_active:
            raise ValidationFailed(
                f"{product.name} is no longer in the shop.", field="reference_id"
            )
        return product, variant

    async def price(
        self, session: AsyncSession, request: LineRequest, *, club_id: UUID
    ) -> PricedLine:
        product, variant = await self._resolve(session, request.reference_id, club_id)
        if variant.stock < request.quantity:
            raise ValidationFailed(
                f"Only {variant.stock} left of {product.name} ({variant.label}).",
                field="quantity",
                available=variant.stock,
            )
        return PricedLine(
            # The label is part of the description because "Scarf" on a receipt
            # does not tell the person at the counter which one to hand over.
            description=f"{product.name} · {variant.label}",
            unit_price=Money(product.price_minor, product.currency),
            quantity=request.quantity,
        )

    async def fulfil(
        self, session: AsyncSession, request: LineRequest, *, club_id: UUID
    ) -> None:
        product, variant = await self._resolve(session, request.reference_id, club_id)
        if variant.stock < request.quantity:
            # Priced a moment ago, gone now: someone else checked out first.
            # Raising here rolls the whole order back, which is the right answer
            # while payment is taken at the counter — nobody has been charged.
            raise ValidationFailed(
                f"{product.name} ({variant.label}) sold out while you were checking out.",
                field="quantity",
                available=variant.stock,
            )
        variant.stock -= request.quantity

    async def reverse(
        self, session: AsyncSession, request: LineRequest, *, club_id: UUID
    ) -> None:
        _, variant = await self._resolve(session, request.reference_id, club_id)
        variant.stock += request.quantity


register(ProductLineHandler())
