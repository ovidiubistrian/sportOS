"""The club shop's catalogue.

A product is the thing on the shelf; a variant is what you actually buy, and it
is the variant that carries stock and the SKU. Even a product with one size gets
a variant — "One size" — because otherwise stock lives in two places depending
on whether a product happens to have sizes, and every query has to handle both.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantScoped, Timestamped, UUIDPrimaryKey


class Product(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    __tablename__ = "product"
    __table_args__ = (
        UniqueConstraint("tenant_id", "club_id", "slug", name="uq_product_slug"),
        UniqueConstraint("tenant_id", "id", name="uq_product_tenant_id_id"),
        CheckConstraint("price_minor >= 0", name="product_price_non_negative"),
        Index("ix_product_club_active", "tenant_id", "club_id", "is_active"),
    )

    club_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    slug: Mapped[str] = mapped_column(String(160))
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)

    price_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))

    cover_media_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    is_active: Mapped[bool] = mapped_column(default=True)
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0)


class ProductVariant(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """What is actually bought: a size, a colour, or "One size".

    `stock` is a plain count rather than a reservation ledger. That is honest
    for Gate 1 — the club shop sells a few hundred scarves a season, not a
    ticket allocation — and the handler decrements it inside the checkout
    transaction, so two supporters buying the last one cannot both succeed.
    """

    __tablename__ = "product_variant"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["product.tenant_id", "product.id"],
            name="fk_variant_product",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_variant_tenant_id_id"),
        CheckConstraint("stock >= 0", name="variant_stock_non_negative"),
        Index("ix_variant_product", "tenant_id", "product_id"),
    )

    product_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    label: Mapped[str] = mapped_column(String(48))
    sku: Mapped[str | None] = mapped_column(String(64))
    stock: Mapped[int] = mapped_column(Integer, default=0)
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0)
