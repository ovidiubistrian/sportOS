from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.core.models import Base, GlobalModel

ACTOR_KINDS = ("USER", "SYSTEM", "PLATFORM", "SCANNER", "API_KEY")


class AuditLog(Base, GlobalModel):
    """Append-only record of sensitive and important actions.

    Range-partitioned by month. Doing that now rather than later is deliberate:
    converting a table with hundreds of millions of rows to partitioned means
    copying it, while creating it partitioned costs one migration today.

    `tenant_id` is nullable because platform actions have no tenant, which is
    why this is a `GlobalModel` — but it still carries an RLS policy so a tenant
    session sees only its own rows. Platform-scoped rows (tenant_id NULL) are
    invisible to every tenant.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        # The partition key must be part of the primary key.
        Index("ix_audit_tenant_time", "tenant_id", "occurred_at"),
        Index("ix_audit_object", "tenant_id", "object_type", "object_id", "occurred_at"),
        Index("ix_audit_actor", "actor_user_id", "occurred_at"),
        CheckConstraint("actor_kind IN " + str(ACTOR_KINDS), name="audit_actor_kind_valid"),
        {"postgresql_partition_by": "RANGE (occurred_at)"},
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_id)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, server_default=func.now()
    )

    tenant_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    club_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    actor_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    actor_kind: Mapped[str] = mapped_column(String(16), default="USER")
    # Set for the whole duration of a support impersonation session, so every
    # action taken on a customer's behalf is attributable to a named operator.
    impersonated_by_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    action: Mapped[str] = mapped_column(String(96))
    object_type: Mapped[str] = mapped_column(String(64))
    object_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    # Both pass through a per-object-type field allow-list before being written.
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)

    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(String(64))
    context: Mapped[dict | None] = mapped_column(JSONB)
