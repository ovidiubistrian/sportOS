"""Outbox relay.

Claims pending events and dispatches them to their handlers. Safe to run in
several replicas: `FOR UPDATE SKIP LOCKED` lets each worker take a disjoint
batch without contention or duplication — the well-trodden Postgres queue
pattern, and the reason a dedicated broker buys us nothing at our volume
(ADR-0008).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select, text, update

from app.core.db import platform_session
from app.events.base import EVENT_TYPES, DomainEvent
from app.events.models import MAX_ATTEMPTS, RETRY_BACKOFF, OutboxEvent
from app.events.registry import subscribers_for

log = structlog.get_logger(__name__)

BATCH_SIZE = 100


def _rehydrate(row: OutboxEvent) -> DomainEvent | None:
    event_class = EVENT_TYPES.get(row.event_type)
    if event_class is None:
        # A rolling deploy can produce events a replica does not yet know. Leave
        # them PENDING rather than failing them — the next version handles them.
        log.warning("event_type_unknown", event_type=row.event_type)
        return None
    return event_class(
        id=row.id,
        aggregate_id=row.aggregate_id,
        tenant_id=row.tenant_id,
        payload=row.payload or {},
        occurred_at=row.occurred_at,
        correlation_id=row.correlation_id,
        causation_id=row.causation_id,
    )


async def _claim_batch(limit: int) -> list[OutboxEvent]:
    """Atomically take up to `limit` due events."""
    async with platform_session(reason="outbox relay claim", routine=True) as session:
        subquery = (
            select(OutboxEvent.id)
            .where(
                OutboxEvent.status == "PENDING",
                OutboxEvent.available_at <= datetime.now(UTC),
            )
            .order_by(OutboxEvent.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        result = await session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id.in_(subquery))
            .values(status="PUBLISHING", attempts=OutboxEvent.attempts + 1)
            .returning(OutboxEvent)
        )
        return list(result.scalars().all())


async def _mark(event_id, *, status: str, error: str | None = None) -> None:
    async with platform_session(reason="outbox relay mark", routine=True) as session:
        values: dict[str, object] = {"status": status, "last_error": error}
        if status == "PUBLISHED":
            values["published_at"] = datetime.now(UTC)
        await session.execute(
            update(OutboxEvent).where(OutboxEvent.id == event_id).values(**values)
        )


async def _reschedule(row: OutboxEvent, error: str) -> None:
    if row.attempts >= MAX_ATTEMPTS:
        log.error(
            "event_dead",
            event_id=str(row.id),
            event_type=row.event_type,
            attempts=row.attempts,
            error=error,
        )
        await _mark(row.id, status="DEAD", error=error)
        return

    delay = RETRY_BACKOFF[min(row.attempts, len(RETRY_BACKOFF) - 1)]
    async with platform_session(reason="outbox relay retry", routine=True) as session:
        await session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id == row.id)
            .values(
                status="PENDING",
                last_error=error,
                available_at=datetime.now(UTC) + timedelta(seconds=delay),
            )
        )
    log.warning(
        "event_retry_scheduled",
        event_id=str(row.id),
        attempt=row.attempts,
        delay_seconds=delay,
    )


async def dispatch_once(limit: int = BATCH_SIZE) -> int:
    """Claim and dispatch one batch. Returns how many events were handled."""
    rows = await _claim_batch(limit)
    if not rows:
        return 0

    for row in rows:
        event = _rehydrate(row)
        if event is None:
            await _mark(row.id, status="PENDING", error="unknown event type")
            continue

        subscriptions = subscribers_for(row.event_type)
        if not subscriptions:
            # Nobody is listening. That is a normal state for an event published
            # ahead of its consumer, not a failure.
            await _mark(row.id, status="PUBLISHED")
            continue

        failures: list[str] = []
        for subscription in subscriptions:
            try:
                await subscription.handler(event)
            except Exception as exc:
                log.exception(
                    "event_handler_failed",
                    handler=subscription.name,
                    event_type=row.event_type,
                    event_id=str(row.id),
                )
                failures.append(f"{subscription.name}: {exc}")

        if failures:
            # Retry the whole event; handlers that already succeeded are
            # protected by their processed_event claim, so they no-op.
            await _reschedule(row, "; ".join(failures)[:2000])
        else:
            await _mark(row.id, status="PUBLISHED")

    return len(rows)


async def cleanup_published(older_than_days: int = 7) -> int:
    """Delete delivered events. Keeps the pending index small and cheap."""
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    async with platform_session(reason="outbox cleanup", routine=True) as session:
        result = await session.execute(
            text(
                "DELETE FROM outbox_event WHERE status = 'PUBLISHED' AND published_at < :cutoff"
            ),
            {"cutoff": cutoff},
        )
        return int(result.rowcount or 0)
