from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, GlobalModel, Timestamped, UUIDPrimaryKey

FEATURE_KINDS = ("BOOLEAN", "LIMIT", "QUOTA")
SUBSCRIPTION_STATUSES = ("TRIALING", "ACTIVE", "PAST_DUE", "PAUSED", "CANCELLED")
ENTITLEMENT_SOURCES = ("PLAN", "OVERRIDE", "TRIAL", "PROMO")
BILLING_INTERVALS = ("MONTH", "YEAR")


class FeatureRecord(Base, Timestamped, GlobalModel):
    """Projection of `app/billing/features.py`, so plans can reference it by FK."""

    __tablename__ = "feature"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    module: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(120))
    default_enabled: Mapped[bool] = mapped_column(default=False)
    default_limit: Mapped[int | None] = mapped_column(BigInteger)

    __table_args__ = (
        CheckConstraint("kind IN " + str(FEATURE_KINDS), name="feature_kind_valid"),
    )


class Plan(Base, UUIDPrimaryKey, Timestamped, GlobalModel):
    __tablename__ = "plan"
    __table_args__ = (UniqueConstraint("key", name="uq_plan_key"),)

    key: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(120))
    tier: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    is_public: Mapped[bool] = mapped_column(default=True)
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0)


class PlanVersion(Base, UUIDPrimaryKey, Timestamped, GlobalModel):
    """A frozen snapshot of what a plan includes.

    Subscriptions pin a version, so a pricing or packaging change never silently
    alters what an existing customer agreed to. Grandfathering comes for free,
    and "what exactly did this tenant buy in March?" stays answerable.
    """

    __tablename__ = "plan_version"
    __table_args__ = (
        UniqueConstraint("plan_id", "version", name="uq_plan_version_plan_version"),
    )

    plan_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("plan.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(SmallInteger)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)


class PlanFeature(Base, GlobalModel):
    __tablename__ = "plan_feature"

    plan_version_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("plan_version.id", ondelete="CASCADE"),
        primary_key=True,
    )
    feature_key: Mapped[str] = mapped_column(
        String(64), ForeignKey("feature.key", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(default=True)
    # NULL means unlimited — distinct from 0, which means "none allowed".
    limit_value: Mapped[int | None] = mapped_column(BigInteger)


class PlanPrice(Base, UUIDPrimaryKey, Timestamped, GlobalModel):
    __tablename__ = "plan_price"
    __table_args__ = (
        UniqueConstraint(
            "plan_version_id", "currency", "interval", name="uq_plan_price_unique"
        ),
        CheckConstraint(
            "interval IN " + str(BILLING_INTERVALS), name="plan_price_interval_valid"
        ),
        CheckConstraint("amount_minor >= 0", name="plan_price_non_negative"),
    )

    plan_version_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("plan_version.id", ondelete="CASCADE")
    )
    currency: Mapped[str] = mapped_column(String(3))
    interval: Mapped[str] = mapped_column(String(8))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    provider_price_ref: Mapped[str | None] = mapped_column(String(128))


class TenantSubscription(Base, UUIDPrimaryKey, Timestamped, GlobalModel):
    __tablename__ = "tenant_subscription"
    __table_args__ = (
        Index(
            "ix_subscription_live",
            "tenant_id",
            postgresql_where="status IN ('TRIALING','ACTIVE','PAST_DUE')",
        ),
        CheckConstraint(
            "status IN " + str(SUBSCRIPTION_STATUSES), name="subscription_status_valid"
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE")
    )
    plan_version_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("plan_version.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(16), default="TRIALING")
    currency: Mapped[str] = mapped_column(String(3), default="EUR")

    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_subscription_ref: Mapped[str | None] = mapped_column(String(128))


class Entitlement(Base, UUIDPrimaryKey, Timestamped, GlobalModel):
    """A per-tenant override on top of the plan.

    Overrides exist because enterprise deals always contain exceptions. Each
    carries who granted it and why, and is time-bounded — so "why does this
    tenant have resale enabled?" always has an answer.
    """

    __tablename__ = "entitlement"
    __table_args__ = (
        Index("ix_entitlement_tenant", "tenant_id", "feature_key"),
        CheckConstraint(
            "source IN " + str(ENTITLEMENT_SOURCES), name="entitlement_source_valid"
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE")
    )
    feature_key: Mapped[str] = mapped_column(
        String(64), ForeignKey("feature.key", ondelete="CASCADE")
    )
    source: Mapped[str] = mapped_column(String(16), default="OVERRIDE")
    enabled: Mapped[bool] = mapped_column(default=True)
    limit_value: Mapped[int | None] = mapped_column(BigInteger)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    granted_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    reason: Mapped[str | None] = mapped_column(Text)
