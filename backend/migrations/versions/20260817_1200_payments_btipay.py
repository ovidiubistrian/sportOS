"""payments: credentials, call journal, attempts

Revision ID: c4e91a7b0d38
Revises: b1d7c40a9e52
Created: 2026-08-17 12:00:00.000000+00:00

Card payments for the club shop, through BT iPay to begin with.

Three tables and one new order status. The tables are tenant-scoped and get
RLS like every other: a gateway's credentials are the last thing that should
be readable across a tenant boundary.

`AWAITING_PAYMENT` is the state between a supporter pressing pay and the bank
saying what happened. Without it that order would sit in `PENDING`, which is
also the state of an order nobody has tried to pay for — and the two have to be
told apart, because one of them must never be cancelled out from under a
supporter who is on their bank's authentication screen.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.rls import disable_all, enable_all, lift_force, restore_force

revision: str = "c4e91a7b0d38"
down_revision: str | None = "b1d7c40a9e52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_TABLES = ["payment_credential", "payment_provider_call", "payment_attempt"]

_OLD_STATUSES = "('PENDING', 'AWAITING_COLLECTION', 'COLLECTED', 'CANCELLED')"
_NEW_STATUSES = (
    "('PENDING', 'AWAITING_PAYMENT', 'AWAITING_COLLECTION', 'COLLECTED', 'CANCELLED')"
)


def upgrade() -> None:
    op.create_table(
        "payment_credential",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column(
            "settings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("is_live", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_payment_credential"),
        sa.UniqueConstraint("tenant_id", "provider", name="uq_payment_credential"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_payment_credential_tenant_id_id"),
        sa.CheckConstraint("provider IN ('btipay')", name="payment_provider_known"),
    )
    op.create_index("ix_payment_credential_tenant_id", "payment_credential", ["tenant_id"])

    op.create_table(
        "payment_provider_call",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("endpoint", sa.String(length=120), nullable=False),
        sa.Column("order_ref", sa.String(length=64), nullable=True),
        sa.Column("provider_order_id", sa.String(length=64), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=32), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "sent",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "received",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_payment_provider_call"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_payment_provider_call_tenant_id_id"),
    )
    op.create_index(
        "ix_payment_provider_call_tenant_id", "payment_provider_call", ["tenant_id"]
    )
    op.create_index(
        "ix_payment_call_order",
        "payment_provider_call",
        ["tenant_id", "order_ref", "created_at"],
    )
    op.create_index(
        "ix_payment_call_provider_order",
        "payment_provider_call",
        ["tenant_id", "provider_order_id"],
    )

    op.create_table(
        "payment_attempt",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_payment_attempt"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_payment_attempt_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id", "provider", "session_id", name="uq_payment_attempt_session"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "order_id"],
            ["shop_order.tenant_id", "shop_order.id"],
            name="fk_payment_attempt_order",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_payment_attempt_tenant_id", "payment_attempt", ["tenant_id"])
    op.create_index(
        "ix_payment_attempt_order",
        "payment_attempt",
        ["tenant_id", "order_id", "created_at"],
    )
    op.create_index("ix_payment_attempt_open", "payment_attempt", ["tenant_id", "settled_at"])

    for statement in enable_all(RLS_TABLES):
        op.execute(statement)

    # The order status a card payment passes through.
    op.drop_constraint("order_status_valid", "shop_order", type_="check")
    op.create_check_constraint("order_status_valid", "shop_order", f"status IN {_NEW_STATUSES}")


def downgrade() -> None:
    # Orders mid-payment have nowhere to go in the old vocabulary. `PENDING`
    # is where they came from and is the safe direction: an order that was
    # about to be paid becomes one nobody has paid, which is recoverable.
    # `shop_order` carries FORCE ROW LEVEL SECURITY, so this UPDATE matches no
    # rows as the migrator — and the constraint recreated just below would then
    # reject any order still sitting in AWAITING_PAYMENT, blocking the whole
    # downgrade. See `lift_force`.
    for statement in lift_force(["shop_order"]):
        op.execute(statement)
    try:
        op.execute("UPDATE shop_order SET status = 'PENDING' WHERE status = 'AWAITING_PAYMENT'")
    finally:
        for statement in restore_force(["shop_order"]):
            op.execute(statement)
    op.drop_constraint("order_status_valid", "shop_order", type_="check")
    op.create_check_constraint("order_status_valid", "shop_order", f"status IN {_OLD_STATUSES}")

    for statement in disable_all(RLS_TABLES):
        op.execute(statement)
    op.drop_table("payment_attempt")
    op.drop_table("payment_provider_call")
    op.drop_table("payment_credential")
