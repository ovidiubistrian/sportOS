"""The ordering kernel: carts, orders and lines.

One order model for everything the club sells (ADR-0005). Today that is shop
products; at Gate 2 it is tickets, memberships and donations, and the reason
they can share a checkout is that nothing here knows what a product is. A line
carries a `line_type` and a `reference_id`, and a handler registered by the
owning module knows what that points at.

The polymorphic reference has no database foreign key — that is the cost the ADR
accepted, and it is why `line_type` is constrained to the registry's keys and why
the description and price are *snapshotted* onto the line. An order has to still
read correctly after the product it refers to is renamed, repriced or deleted.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
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

LINE_TYPES = ("PRODUCT", "TICKET", "SEASON_TICKET", "MEMBERSHIP", "DONATION")

CART_STATUSES = ("OPEN", "CONVERTED", "ABANDONED")

# A shop order's life. `AWAITING_COLLECTION` is where a pay-on-collection order
# sits between checkout and the supporter turning up at the club shop.
ORDER_STATUSES = (
    "PENDING",
    "AWAITING_COLLECTION",
    "COLLECTED",
    "CANCELLED",
)

PAYMENT_METHODS = ("ON_COLLECTION", "CARD")


class Cart(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """A basket in progress, held server-side.

    Server-side rather than in the browser because a line has to be able to
    reserve stock, and a reservation the server does not know about is not a
    reservation. Identified by an opaque token in a cookie: a supporter buying a
    scarf should not have to make an account first.
    """

    __tablename__ = "cart"
    __table_args__ = (
        UniqueConstraint("token", name="uq_cart_token"),
        UniqueConstraint("tenant_id", "id", name="uq_cart_tenant_id_id"),
        CheckConstraint("status IN " + str(CART_STATUSES), name="cart_status_valid"),
        Index("ix_cart_club_status", "tenant_id", "club_id", "status"),
    )

    club_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    token: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="OPEN")
    currency: Mapped[str] = mapped_column(String(3))
    # Carts are swept, not kept: an abandoned one holds no stock after this.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CartLine(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    __tablename__ = "cart_line"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "cart_id"],
            ["cart.tenant_id", "cart.id"],
            name="fk_cart_line_cart",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "cart_id", "line_type", "reference_id", name="uq_cart_line_reference"
        ),
        CheckConstraint("line_type IN " + str(LINE_TYPES), name="cart_line_type_valid"),
        CheckConstraint("quantity > 0", name="cart_line_quantity_positive"),
    )

    cart_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    line_type: Mapped[str] = mapped_column(String(16))
    reference_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    quantity: Mapped[int] = mapped_column(SmallInteger, default=1)


class Order(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """A placed order.

    Money is stored in minor units, as an integer, everywhere. See
    `app/core/money.py` — a float here is a rounding error somebody eventually
    has to refund.
    """

    __tablename__ = "shop_order"
    __table_args__ = (
        UniqueConstraint("tenant_id", "reference", name="uq_order_reference"),
        UniqueConstraint("tenant_id", "id", name="uq_order_tenant_id_id"),
        CheckConstraint("status IN " + str(ORDER_STATUSES), name="order_status_valid"),
        CheckConstraint(
            "payment_method IN " + str(PAYMENT_METHODS), name="order_payment_valid"
        ),
        CheckConstraint("total_minor >= 0", name="order_total_non_negative"),
        Index("ix_order_club_status", "tenant_id", "club_id", "status"),
        Index("ix_order_placed", "tenant_id", "club_id", "placed_at"),
    )

    club_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    # Short and human: what the supporter reads out at the counter.
    reference: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default="PENDING")
    currency: Mapped[str] = mapped_column(String(3))
    subtotal_minor: Mapped[int] = mapped_column(Integer, default=0)
    total_minor: Mapped[int] = mapped_column(Integer, default=0)

    buyer_name: Mapped[str] = mapped_column(String(160))
    buyer_email: Mapped[str | None] = mapped_column(String(320))
    buyer_phone: Mapped[str | None] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text)

    # Set when the buyer was signed in. Null for a guest checkout, which stays
    # supported: making somebody create an account to buy a scarf is how a club
    # loses the sale.
    supporter_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    payment_method: Mapped[str] = mapped_column(String(16), default="ON_COLLECTION")
    placed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrderLine(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """One line of an order, with its price and description snapshotted.

    Deliberately denormalised. The club will rename products, change prices and
    delete lines it no longer stocks; none of that may change what a supporter
    was charged, or what the receipt says they bought.
    """

    __tablename__ = "shop_order_line"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "order_id"],
            ["shop_order.tenant_id", "shop_order.id"],
            name="fk_order_line_order",
            ondelete="CASCADE",
        ),
        CheckConstraint("line_type IN " + str(LINE_TYPES), name="order_line_type_valid"),
        CheckConstraint("quantity > 0", name="order_line_quantity_positive"),
    )

    order_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    line_type: Mapped[str] = mapped_column(String(16))
    reference_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))

    description: Mapped[str] = mapped_column(String(240))
    unit_price_minor: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(SmallInteger)
    total_minor: Mapped[int] = mapped_column(Integer)
