from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantScoped, UUIDPrimaryKey

AI_OPERATIONS = ("POLISH", "HEADLINES")


class AiUsage(Base, UUIDPrimaryKey, TenantScoped):
    """Append-only record of every assistant call.

    The platform pays for these on one shared key, so metering is not optional:
    without a per-tenant ledger there is no way to enforce a quota, attribute
    cost, or notice a single tenant burning the budget for everyone.

    Tenant-scoped and under RLS, so a tenant reads only its own meter. The
    platform reads across tenants through `platform_session` to bill and to spot
    a single tenant burning the shared budget — the same route the audit log
    uses, and equally visible in the logs.
    """

    __tablename__ = "ai_usage"
    __table_args__ = (
        # The quota query: usage for one tenant in the current period.
        Index("ix_ai_usage_tenant_period", "tenant_id", "created_at"),
        Index("ix_ai_usage_platform", "created_at"),
        CheckConstraint("operation IN " + str(AI_OPERATIONS), name="ai_usage_operation_valid"),
    )

    club_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    actor_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    operation: Mapped[str] = mapped_column(String(24))
    object_type: Mapped[str] = mapped_column(String(32), default="content_item")
    object_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    model: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    # Whether the editor kept the suggestion. The only honest measure of whether
    # the feature is worth what it costs.
    accepted: Mapped[bool | None] = mapped_column()

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
