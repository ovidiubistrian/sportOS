from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, GlobalModel, UUIDPrimaryKey

OUTBOX_STATUSES = ("PENDING", "PUBLISHING", "PUBLISHED", "FAILED", "DEAD")

# Attempt -> delay in seconds. After the last entry the event is DEAD, alerted
# on, and replayable from the platform UI — never silently dropped.
RETRY_BACKOFF = (1, 5, 30, 120, 600)
MAX_ATTEMPTS = len(RETRY_BACKOFF)


class OutboxEvent(Base, UUIDPrimaryKey, GlobalModel):
    """A domain event, written in the same transaction as the state change.

    Not tenant-scoped: the relay claims rows across all tenants, before any
    tenant context exists. `tenant_id` is carried as data and re-established by
    the handler.
    """

    __tablename__ = "outbox_event"
    __table_args__ = (
        # The relay's only query. Partial so the index stays small even as
        # published rows accumulate before the cleanup job removes them.
        Index(
            "ix_outbox_pending",
            "available_at",
            "id",
            postgresql_where="status = 'PENDING'",
        ),
        Index("ix_outbox_status_created", "status", "occurred_at"),
        CheckConstraint("status IN " + str(OUTBOX_STATUSES), name="outbox_status_valid"),
    )

    tenant_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    aggregate_type: Mapped[str] = mapped_column(String(64))
    aggregate_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))

    event_type: Mapped[str] = mapped_column(String(96))
    event_version: Mapped[int] = mapped_column(SmallInteger, default=1)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)

    correlation_id: Mapped[str | None] = mapped_column(String(64))
    causation_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))


class ProcessedEvent(Base, GlobalModel):
    """Consumer-side idempotency.

    Delivery is at-least-once, so every handler claims its event before doing
    the work. The primary key makes a duplicate delivery a no-op, and the claim
    commits with the effect so a crash between them cannot mark work done that
    never happened.
    """

    __tablename__ = "processed_event"

    handler_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    event_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer)
