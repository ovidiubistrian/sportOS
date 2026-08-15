"""The shop, from the club's side: catalogue and orders."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from app.api.deps import Db, Requires
from app.audit.service import AuditService
from app.billing.features import Feature
from app.commerce.models import Product, ProductVariant
from app.core.context import RequestContext
from app.core.errors import Conflict, NotFound
from app.core.money import exponent_for
from app.identity.registration import slugify
from app.media import storage
from app.media.models import MediaAsset
from app.ordering.models import Order, OrderLine
from app.ordering.service import OrderingService
from app.tenants.models import Club

router = APIRouter(tags=["shop"])

SHOP = Feature.SHOP
READ = "commerce.product.read"
MANAGE = "commerce.product.manage"
ORDERS_READ = "commerce.order.read"
ORDERS_MANAGE = "commerce.order.manage"


class VariantIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID | None = None
    label: str = Field(min_length=1, max_length=48)
    sku: str | None = Field(default=None, max_length=64)
    stock: int = Field(default=0, ge=0, le=1_000_000)
    sort_order: int = 0


class VariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    label: str
    sku: str | None
    stock: int
    sort_order: int


class ProductOut(BaseModel):
    id: UUID
    club_id: UUID
    slug: str
    name: str
    description: str | None
    price_minor: int
    currency: str
    cover_media_id: UUID | None
    cover_url: str | None
    is_active: bool
    sort_order: int
    variants: list[VariantOut]


class ProductIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    club_id: UUID
    name: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    price_minor: int = Field(ge=0, le=100_000_000)
    cover_media_id: UUID | None = None
    is_active: bool = True
    sort_order: int = 0
    # A product with no sizes still gets one variant; the service names it.
    variants: list[VariantIn] = Field(default_factory=list, max_length=24)


class ProductUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    price_minor: int | None = Field(default=None, ge=0, le=100_000_000)
    cover_media_id: UUID | None = None
    is_active: bool | None = None
    sort_order: int | None = None
    variants: list[VariantIn] | None = Field(default=None, max_length=24)


class OrderLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    description: str
    unit_price_minor: int
    quantity: int
    total_minor: int


class OrderOut(BaseModel):
    id: UUID
    reference: str
    status: str
    currency: str
    total_minor: int
    buyer_name: str
    buyer_email: str | None
    buyer_phone: str | None
    note: str | None
    placed_at: datetime | None
    collected_at: datetime | None
    lines: list[OrderLineOut]


class OrderAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str

    @field_validator("status")
    @classmethod
    def _known(cls, value: str) -> str:
        if value not in ("COLLECTED", "CANCELLED"):
            raise ValueError("must be COLLECTED or CANCELLED")
        return value


# --- catalogue --------------------------------------------------------------


async def _render(db: Db, products: list[Product]) -> list[ProductOut]:
    if not products:
        return []

    variants: dict[UUID, list[ProductVariant]] = {p.id: [] for p in products}
    for variant in await db.scalars(
        select(ProductVariant)
        .where(ProductVariant.product_id.in_(variants))
        .order_by(ProductVariant.sort_order, ProductVariant.label)
    ):
        variants[variant.product_id].append(variant)

    cover_ids = {p.cover_media_id for p in products if p.cover_media_id}
    covers = (
        {
            asset.id: storage.public_url(asset.storage_key)
            for asset in await db.scalars(
                select(MediaAsset).where(MediaAsset.id.in_(cover_ids))
            )
        }
        if cover_ids
        else {}
    )

    return [
        ProductOut(
            id=product.id,
            club_id=product.club_id,
            slug=product.slug,
            name=product.name,
            description=product.description,
            price_minor=product.price_minor,
            currency=product.currency,
            cover_media_id=product.cover_media_id,
            cover_url=covers.get(product.cover_media_id) if product.cover_media_id else None,
            is_active=product.is_active,
            sort_order=product.sort_order,
            variants=[VariantOut.model_validate(v) for v in variants[product.id]],
        )
        for product in products
    ]


async def _sync_variants(
    db: Db, product: Product, wanted: list[VariantIn], tenant_id: UUID
) -> None:
    """Reconcile a product's variants against what the form submitted.

    Variants are matched by id, not by position: a club reordering sizes must
    not silently move the stock count from Medium onto Large. A variant that
    disappears from the list is deleted — its stock goes with it, which is
    correct, because the club is saying it does not stock that size.
    """
    if not wanted:
        wanted = [VariantIn(label="One size")]

    existing = {
        v.id: v
        for v in await db.scalars(
            select(ProductVariant).where(ProductVariant.product_id == product.id)
        )
    }
    kept: set[UUID] = set()

    for index, spec in enumerate(wanted):
        variant = existing.get(spec.id) if spec.id else None
        if variant is None:
            variant = ProductVariant(
                tenant_id=tenant_id,
                product_id=product.id,
                label=spec.label.strip(),
                sku=spec.sku,
                stock=spec.stock,
                sort_order=spec.sort_order or index,
            )
            db.add(variant)
        else:
            variant.label = spec.label.strip()
            variant.sku = spec.sku
            variant.stock = spec.stock
            variant.sort_order = spec.sort_order or index
            kept.add(variant.id)

    for variant_id, variant in existing.items():
        if variant_id not in kept:
            await db.delete(variant)
    await db.flush()


@router.get("/products", response_model=list[ProductOut], summary="The catalogue")
async def list_products(
    club_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(READ, feature=SHOP))],
    include_inactive: Annotated[bool, Query()] = True,
) -> list[ProductOut]:
    stmt = select(Product).where(
        Product.tenant_id == ctx.tenant, Product.club_id == club_id
    )
    if not include_inactive:
        stmt = stmt.where(Product.is_active.is_(True))
    products = list(await db.scalars(stmt.order_by(Product.sort_order, Product.name)))
    return await _render(db, products)


@router.post(
    "/products",
    response_model=ProductOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a product",
)
async def create_product(
    payload: ProductIn,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(MANAGE, feature=SHOP))],
) -> ProductOut:
    club = await db.scalar(
        select(Club).where(Club.id == payload.club_id, Club.tenant_id == ctx.tenant)
    )
    if club is None:
        raise NotFound(object_type="club", object_id=str(payload.club_id))

    slug = slugify(payload.name)
    duplicate = await db.scalar(
        select(Product.id).where(
            Product.tenant_id == ctx.tenant,
            Product.club_id == payload.club_id,
            Product.slug == slug,
        )
    )
    if duplicate is not None:
        raise Conflict("There is already a product with that name.", field="name")

    product = Product(
        tenant_id=ctx.tenant,
        club_id=payload.club_id,
        slug=slug,
        name=payload.name.strip(),
        description=payload.description,
        price_minor=payload.price_minor,
        # The club's own currency: a shop that prices in something else is a
        # different feature, and guessing one here would be worse than deciding.
        currency=club.currency,
        cover_media_id=payload.cover_media_id,
        is_active=payload.is_active,
        sort_order=payload.sort_order,
    )
    db.add(product)
    await db.flush()
    await _sync_variants(db, product, payload.variants, ctx.tenant)

    AuditService(db).record(
        ctx,
        action="commerce.product.create",
        object_type="product",
        object_id=product.id,
        club_id=payload.club_id,
        after={"name": product.name, "price_minor": product.price_minor},
    )
    return (await _render(db, [product]))[0]


@router.patch("/products/{product_id}", response_model=ProductOut, summary="Edit a product")
async def update_product(
    product_id: UUID,
    payload: ProductUpdate,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(MANAGE, feature=SHOP))],
) -> ProductOut:
    product = await db.scalar(
        select(Product).where(Product.id == product_id, Product.tenant_id == ctx.tenant)
    )
    if product is None:
        raise NotFound(object_type="product", object_id=str(product_id))

    changes = payload.model_dump(exclude_unset=True)
    variants = changes.pop("variants", None)
    before = {field: getattr(product, field) for field in changes}
    for field, value in changes.items():
        setattr(product, field, value)
    if "name" in changes:
        product.name = product.name.strip()

    if variants is not None:
        await _sync_variants(
            db, product, [VariantIn.model_validate(v) for v in variants], ctx.tenant
        )

    AuditService(db).record(
        ctx,
        action="commerce.product.update",
        object_type="product",
        object_id=product.id,
        club_id=product.club_id,
        before=before,
        after=changes,
    )
    await db.flush()
    return (await _render(db, [product]))[0]


@router.delete(
    "/products/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a product",
)
async def delete_product(
    product_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(MANAGE, feature=SHOP))],
) -> None:
    """Deleted, not archived — but only if nobody has bought one.

    Order lines snapshot their description and price, so a deleted product does
    not damage an old receipt. What it would damage is a *pending* order the
    club still has to hand over, so those hold the product in place.
    """
    product = await db.scalar(
        select(Product).where(Product.id == product_id, Product.tenant_id == ctx.tenant)
    )
    if product is None:
        raise NotFound(object_type="product", object_id=str(product_id))

    pending = await db.scalar(
        select(OrderLine.id)
        .join(Order, Order.id == OrderLine.order_id)
        .join(ProductVariant, ProductVariant.id == OrderLine.reference_id)
        .where(
            ProductVariant.product_id == product.id,
            Order.status == "AWAITING_COLLECTION",
        )
        .limit(1)
    )
    if pending is not None:
        raise Conflict(
            "Someone is waiting to collect this. Hide it from the shop instead.",
            field="is_active",
        )

    AuditService(db).record(
        ctx,
        action="commerce.product.delete",
        object_type="product",
        object_id=product.id,
        club_id=product.club_id,
        before={"name": product.name},
    )
    await db.delete(product)
    await db.flush()


# --- orders -----------------------------------------------------------------


async def _order_out(db: Db, orders: list[Order]) -> list[OrderOut]:
    if not orders:
        return []
    lines: dict[UUID, list[OrderLine]] = {o.id: [] for o in orders}
    for line in await db.scalars(
        select(OrderLine).where(OrderLine.order_id.in_(lines)).order_by(OrderLine.created_at)
    ):
        lines[line.order_id].append(line)

    return [
        OrderOut(
            id=order.id,
            reference=order.reference,
            status=order.status,
            currency=order.currency,
            total_minor=order.total_minor,
            buyer_name=order.buyer_name,
            buyer_email=order.buyer_email,
            buyer_phone=order.buyer_phone,
            note=order.note,
            placed_at=order.placed_at,
            collected_at=order.collected_at,
            lines=[OrderLineOut.model_validate(line) for line in lines[order.id]],
        )
        for order in orders
    ]


@router.get("/orders", response_model=list[OrderOut], summary="Shop orders")
async def list_orders(
    club_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(ORDERS_READ, feature=SHOP))],
    status_: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[OrderOut]:
    stmt = select(Order).where(Order.tenant_id == ctx.tenant, Order.club_id == club_id)
    if status_:
        stmt = stmt.where(Order.status == status_)
    orders = list(await db.scalars(stmt.order_by(Order.placed_at.desc()).limit(limit)))
    return await _order_out(db, orders)


@router.post("/orders/{order_id}/status", response_model=OrderOut, summary="Collect or cancel")
async def act_on_order(
    order_id: UUID,
    payload: OrderAction,
    club_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(ORDERS_MANAGE, feature=SHOP))],
) -> OrderOut:
    service = OrderingService(db)
    order = await service.get_order(order_id, club_id)

    before = order.status
    if payload.status == "COLLECTED":
        await service.collect(order)
    else:
        await service.cancel(order)

    AuditService(db).record(
        ctx,
        action="commerce.order.update",
        object_type="order",
        object_id=order.id,
        club_id=club_id,
        before={"status": before},
        after={"status": order.status},
    )
    await db.flush()
    return (await _order_out(db, [order]))[0]


@router.get("/currency-exponent/{currency}", include_in_schema=False)
async def currency_exponent(currency: str) -> dict[str, int]:
    """Used by the admin's price field to place the decimal point."""
    return {"exponent": exponent_for(currency)}
