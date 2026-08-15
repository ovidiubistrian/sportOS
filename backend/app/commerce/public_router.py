"""The shop as a supporter sees it: browse, basket, checkout.

Unauthenticated by design, like the rest of the public site. A supporter is
identified by an opaque cart token they were handed on their first `POST`, and
by nothing else — buying a scarf should not require making an account, and
asking for one is how a club loses the sale.

Everything here is scoped by the `Host` the visitor arrived on. There is no
club or tenant parameter, deliberately: a request parameter that selects a
tenant is the one thing the tenancy design forbids.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select

from app.commerce.models import Product, ProductVariant
from app.core.db import tenant_session
from app.core.errors import NotFound
from app.fans.supporter_service import optional_subject, supporter_id_for
from app.media import storage
from app.media.models import MediaAsset
from app.ordering.models import OrderLine
from app.ordering.service import OrderingService
from app.tenants.models import Club
from app.tenants.site_service import SiteRoute, resolve_host

router = APIRouter(prefix="/public", tags=["public"])

# Short: stock moves, and a supporter looking at "2 left" needs it to be true.
SHOP_CACHE = "public, max-age=30, stale-while-revalidate=120"


class PublicVariant(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    label: str
    # The count itself, not a boolean: "2 left" sells, "in stock" does not.
    stock: int


class PublicProduct(BaseModel):
    id: UUID
    slug: str
    name: str
    description: str | None
    price_minor: int
    currency: str
    cover_url: str | None
    variants: list[PublicVariant]


class BasketLine(BaseModel):
    variant_id: UUID
    product_name: str
    variant_label: str
    unit_price_minor: int
    quantity: int
    total_minor: int
    cover_url: str | None


class Basket(BaseModel):
    token: str
    currency: str
    lines: list[BasketLine]
    total_minor: int


class SetLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variant_id: UUID
    quantity: int = Field(ge=0, le=20)


class CheckoutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=160)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)
    note: str | None = Field(default=None, max_length=500)


class PlacedOrder(BaseModel):
    reference: str
    total_minor: int
    currency: str
    buyer_name: str
    lines: list[BasketLine]


def _host(forwarded: str | None, header_host: str | None) -> str | None:
    return (forwarded or header_host or "").split(",")[0].strip() or None


async def _route_or_404(host: str | None) -> SiteRoute:
    route = await resolve_host(host)
    if route is None:
        raise NotFound("No club is published on this domain.")
    return route


async def _covers(session, products: list[Product]) -> dict[UUID, str]:
    ids = {p.cover_media_id for p in products if p.cover_media_id}
    if not ids:
        return {}
    return {
        asset.id: storage.public_url(asset.storage_key)
        for asset in await session.scalars(select(MediaAsset).where(MediaAsset.id.in_(ids)))
    }


@router.get("/shop", response_model=list[PublicProduct], summary="The club shop")
async def public_shop(
    response: Response,
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    host: Annotated[str | None, Header(alias="Host")] = None,
) -> list[PublicProduct]:
    route = await _route_or_404(_host(x_forwarded_host, host))
    response.headers["Cache-Control"] = SHOP_CACHE

    async with tenant_session(route.tenant_id) as session:
        products = list(
            await session.scalars(
                select(Product)
                .where(Product.club_id == route.club_id, Product.is_active.is_(True))
                .order_by(Product.sort_order, Product.name)
            )
        )
        if not products:
            return []

        variants: dict[UUID, list[ProductVariant]] = {p.id: [] for p in products}
        for variant in await session.scalars(
            select(ProductVariant)
            .where(ProductVariant.product_id.in_(variants))
            .order_by(ProductVariant.sort_order, ProductVariant.label)
        ):
            variants[variant.product_id].append(variant)

        covers = await _covers(session, products)
        return [
            PublicProduct(
                id=product.id,
                slug=product.slug,
                name=product.name,
                description=product.description,
                price_minor=product.price_minor,
                currency=product.currency,
                cover_url=covers.get(product.cover_media_id)
                if product.cover_media_id
                else None,
                variants=[PublicVariant.model_validate(v) for v in variants[product.id]],
            )
            for product in products
        ]


async def _basket(session, route: SiteRoute, cart) -> Basket:
    service = OrderingService(session)
    lines = await service.lines_of(cart)
    if not lines:
        return Basket(token=cart.token, currency=cart.currency, lines=[], total_minor=0)

    rows = (
        await session.execute(
            select(ProductVariant, Product)
            .join(Product, Product.id == ProductVariant.product_id)
            .where(ProductVariant.id.in_([line.reference_id for line in lines]))
        )
    ).all()
    by_variant = {variant.id: (variant, product) for variant, product in rows}
    covers = await _covers(session, [product for _, product in rows])

    out: list[BasketLine] = []
    total = 0
    for line in lines:
        found = by_variant.get(line.reference_id)
        if found is None:
            # Withdrawn while the basket sat there. Silently dropping it is
            # kinder than a basket that cannot be checked out and will not say
            # which line is the problem.
            await session.delete(line)
            continue
        variant, product = found
        line_total = product.price_minor * line.quantity
        total += line_total
        out.append(
            BasketLine(
                variant_id=variant.id,
                product_name=product.name,
                variant_label=variant.label,
                unit_price_minor=product.price_minor,
                quantity=line.quantity,
                total_minor=line_total,
                cover_url=covers.get(product.cover_media_id)
                if product.cover_media_id
                else None,
            )
        )

    return Basket(token=cart.token, currency=cart.currency, lines=out, total_minor=total)


@router.get("/basket", response_model=Basket, summary="What is in the basket")
async def get_basket(
    response: Response,
    x_cart_token: Annotated[str | None, Header(alias="X-Cart-Token")] = None,
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    host: Annotated[str | None, Header(alias="Host")] = None,
) -> Basket:
    route = await _route_or_404(_host(x_forwarded_host, host))
    response.headers["Cache-Control"] = "no-store"

    async with tenant_session(route.tenant_id) as session:
        club = await session.get(Club, route.club_id)
        service = OrderingService(session)
        cart = await service.get_cart(x_cart_token, route.club_id) if x_cart_token else None
        if cart is None:
            cart = await service.open_cart(
                route.tenant_id, route.club_id, club.currency if club else "EUR"
            )
        return await _basket(session, route, cart)


@router.put("/basket/lines", response_model=Basket, summary="Set a line's quantity")
async def set_basket_line(
    payload: SetLine,
    response: Response,
    x_cart_token: Annotated[str | None, Header(alias="X-Cart-Token")] = None,
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    host: Annotated[str | None, Header(alias="Host")] = None,
) -> Basket:
    route = await _route_or_404(_host(x_forwarded_host, host))
    response.headers["Cache-Control"] = "no-store"

    async with tenant_session(route.tenant_id) as session:
        club = await session.get(Club, route.club_id)
        service = OrderingService(session)
        cart = await service.get_cart(x_cart_token, route.club_id) if x_cart_token else None
        if cart is None:
            cart = await service.open_cart(
                route.tenant_id, route.club_id, club.currency if club else "EUR"
            )
        await service.set_line(cart, "PRODUCT", payload.variant_id, payload.quantity)
        return await _basket(session, route, cart)


@router.post(
    "/basket/checkout",
    response_model=PlacedOrder,
    status_code=status.HTTP_201_CREATED,
    summary="Place the order",
)
async def checkout(
    payload: CheckoutIn,
    response: Response,
    subject: Annotated[str | None, Depends(optional_subject)],
    x_cart_token: Annotated[str | None, Header(alias="X-Cart-Token")] = None,
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    host: Annotated[str | None, Header(alias="Host")] = None,
) -> PlacedOrder:
    """Reserve nothing, charge nothing, promise a pickup.

    Payment happens at the counter in Gate 1, so the order is placed straight
    into `AWAITING_COLLECTION` and the supporter is given a reference to read
    out. The card flow at Gate 2 slots in between pricing and fulfilment
    without touching anything else here.
    """
    route = await _route_or_404(_host(x_forwarded_host, host))
    response.headers["Cache-Control"] = "no-store"

    if not x_cart_token:
        raise NotFound("Your basket has expired.")

    async with tenant_session(route.tenant_id) as session:
        service = OrderingService(session)
        cart = await service.get_cart(x_cart_token, route.club_id)
        if cart is None:
            raise NotFound("Your basket has expired.")

        basket = await _basket(session, route, cart)
        order = await service.checkout(
            cart,
            buyer_name=payload.name,
            buyer_email=payload.email,
            buyer_phone=payload.phone,
            note=payload.note,
            # A bonus, not a requirement: the order stands either way, and a
            # signed-in supporter simply finds it in their account afterwards.
            supporter_id=await supporter_id_for(
                session, club_id=route.club_id, subject=subject
            ),
        )
        # Read back from the order rather than the basket: what was charged is
        # what the lines say, and the receipt has to agree with the record.
        placed = list(
            await session.scalars(
                select(OrderLine)
                .where(OrderLine.order_id == order.id)
                .order_by(OrderLine.created_at)
            )
        )
        by_variant = {line.variant_id: line for line in basket.lines}
        return PlacedOrder(
            reference=order.reference,
            total_minor=order.total_minor,
            currency=order.currency,
            buyer_name=order.buyer_name,
            lines=[
                BasketLine(
                    variant_id=line.reference_id,
                    product_name=line.description.split(" · ")[0],
                    variant_label=line.description.split(" · ")[-1],
                    unit_price_minor=line.unit_price_minor,
                    quantity=line.quantity,
                    total_minor=line.total_minor,
                    cover_url=(
                        by_variant[line.reference_id].cover_url
                        if line.reference_id in by_variant
                        else None
                    ),
                )
                for line in placed
            ],
        )
