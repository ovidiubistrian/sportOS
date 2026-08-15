"""Scheduled publishing.

An editor writes a match report on Friday and schedules it for Saturday 18:00.
This job flips it live. Run by the relay process on a short interval, alongside
the outbox dispatcher.

It publishes `ContentPublished` through the outbox rather than purging the site
cache directly, so a slow or unavailable public-web delays the purge and never
the publication itself.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy import select

from app.cms.models import ContentItem
from app.core.db import platform_session
from app.events.base import ContentPublished
from app.events.publisher import publish

log = structlog.get_logger(__name__)

BATCH_SIZE = 200


async def publish_due_content() -> list[str]:
    """Publish everything whose scheduled time has passed.

    Runs cross-tenant (the scheduler has no tenant context) and claims rows with
    `FOR UPDATE SKIP LOCKED`, so two relay replicas cannot publish the same
    article twice.
    """
    published: list[str] = []
    now = datetime.now(UTC)

    async with platform_session(reason="publish scheduled content", routine=True) as session:
        due = list(
            await session.scalars(
                select(ContentItem)
                .where(
                    ContentItem.status == "SCHEDULED",
                    ContentItem.scheduled_for <= now,
                )
                .order_by(ContentItem.scheduled_for)
                .limit(BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
        )

        for item in due:
            item.status = "PUBLISHED"
            # The moment the editor chose, not the moment the job happened to
            # run: ordering on the site must match what they scheduled.
            item.published_at = item.scheduled_for or now
            item.scheduled_for = None
            publish(session, ContentPublished.of(item.id, tenant_id=item.tenant_id))
            published.append(str(item.id))

    if published:
        log.info("scheduled_content_published", count=len(published), items=published)
    return published
