"""Publishing and consuming.

`publish()` writes the event into the caller's transaction — the state change
and the event commit together, or neither does. There is no other sanctioned
way to emit an event, because every alternative loses side effects on a crash.
See ADR-0008.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import structlog
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import current_request_id
from app.events.base import DomainEvent
from app.events.models import ProcessedEvent

log = structlog.get_logger(__name__)


def publish(session: AsyncSession, event: DomainEvent) -> None:
    """Queue a domain event for delivery after this transaction commits.

    Synchronous by design: it only adds a row to the session. If the caller
    rolls back, the event disappears with the change that would have caused it.
    """
    from app.events.models import OutboxEvent

    session.add(
        OutboxEvent(
            id=event.id,
            tenant_id=event.tenant_id,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            event_type=event.event_type,
            event_version=event.event_version,
            payload=event.payload,
            occurred_at=event.occurred_at,
            available_at=event.occurred_at,
            correlation_id=event.correlation_id or current_request_id(),
            causation_id=event.causation_id,
        )
    )
    log.debug("event_queued", event_type=event.event_type, event_id=str(event.id))


async def claim(session: AsyncSession, handler_name: str, event_id) -> bool:
    """Take ownership of an event for one handler.

    Returns False when this handler has already processed it — the correct
    response to a duplicate delivery. The claim commits with the handler's
    effect, so partial work cannot be marked complete.
    """
    statement = (
        pg_insert(ProcessedEvent)
        .values(handler_name=handler_name, event_id=event_id)
        .on_conflict_do_nothing(index_elements=["handler_name", "event_id"])
        .returning(ProcessedEvent.event_id)
    )
    return (await session.scalar(statement)) is not None


@asynccontextmanager
async def handler_transaction(
    handler_name: str, event: DomainEvent
) -> AsyncIterator[AsyncSession | None]:
    """A unit of work for one handler, scoped to the event's tenant.

    Yields None when the event was already processed, so the handler body is
    skipped without the caller writing the check itself:

        async with handler_transaction(name, event) as session:
            if session is None:
                return
            ...
    """
    from app.core.db import tenant_session

    started = datetime.now(UTC)
    async with tenant_session(event.tenant_id) as session:
        if not await claim(session, handler_name, event.id):
            log.debug("event_already_processed", handler=handler_name, event_id=str(event.id))
            yield None
            return

        yield session

        elapsed_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
        await session.execute(
            update(ProcessedEvent)
            .where(
                ProcessedEvent.handler_name == handler_name,
                ProcessedEvent.event_id == event.id,
            )
            .values(duration_ms=elapsed_ms)
        )
