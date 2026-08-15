"""Partition maintenance for `audit_log`.

Creates monthly partitions ahead of time. A missing partition means every
audited write fails, so the job runs well in advance (three months) and is
idempotent — running it twice, or when nothing is due, does nothing.

The DDL itself is performed by `create_audit_partition`, a SECURITY DEFINER
function owned by the schema owner. The relay's role may execute that one
function and holds no other DDL rights; see migration 5a7c2e918d64.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import structlog
from sqlalchemy import text

from app.core.db import platform_session

log = structlog.get_logger(__name__)

MONTHS_AHEAD = 3


def _month_start(when: date) -> date:
    return when.replace(day=1)


def _next_month(when: date) -> date:
    return (
        date(when.year + 1, 1, 1) if when.month == 12 else date(when.year, when.month + 1, 1)
    )


def months_to_create(
    months_ahead: int = MONTHS_AHEAD, today: date | None = None
) -> list[date]:
    """The current month plus `months_ahead` following months."""
    start = _month_start(today or datetime.now(UTC).date())
    months = []
    for _ in range(months_ahead + 1):
        months.append(start)
        start = _next_month(start)
    return months


def partition_statements(
    months_ahead: int = MONTHS_AHEAD, today: date | None = None
) -> list[str]:
    """Literal DDL, for use inside migrations where the function does not exist yet."""
    statements = []
    for start in months_to_create(months_ahead, today):
        end = _next_month(start)
        name = f"audit_log_{start:%Y_%m}"
        statements.append(
            f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF audit_log "
            f"FOR VALUES FROM ('{start:%Y-%m-%d}') TO ('{end:%Y-%m-%d}')"
        )
    return statements


async def ensure_audit_partitions(months_ahead: int = MONTHS_AHEAD) -> list[str]:
    created: list[str] = []
    async with platform_session(
        reason="audit partition maintenance", routine=True
    ) as session:
        for month in months_to_create(months_ahead):
            name = await session.scalar(
                text("SELECT create_audit_partition(:month)"), {"month": month}
            )
            created.append(str(name))
    log.debug("audit_partitions_ensured", partitions=created)
    return created
