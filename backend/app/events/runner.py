"""Relay process.

Runs the outbox dispatcher plus the small set of periodic maintenance jobs the
platform needs today (outbox cleanup, audit partition creation).

Why this and not Celery yet
---------------------------
The architecture commits to Celery for background work, and that still holds —
but Celery earns its keep when there is a real task workload (emails, wallet
passes, report generation), all of which arrive in Phase 1. Right now the only
asynchronous work is dispatching the outbox, which needs a long-lived async
process rather than a task queue, and a couple of timers.

Introducing Celery now would mean running a broker, a worker and a beat
scheduler to execute two cron-like jobs, plus bridging sync Celery tasks onto
async SQLAlchemy — machinery with no current payload. The relay is added as a
separate deployable so Celery slots in beside it, not through it, when the
first real task appears.

This is a deliberate deferral, recorded here rather than discovered later.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog

from app.core.logging import configure_logging
from app.core.model_registry import *  # noqa: F403  registers all metadata

log = structlog.get_logger("relay")

POLL_INTERVAL_SECONDS = 0.2
IDLE_INTERVAL_SECONDS = 1.0


@dataclass
class PeriodicJob:
    name: str
    interval: timedelta
    run: object  # async callable
    last_run: datetime | None = None

    def is_due(self, now: datetime) -> bool:
        return self.last_run is None or now - self.last_run >= self.interval


async def _dispatch_loop(stop: asyncio.Event) -> None:
    from app.events.relay import BATCH_SIZE, dispatch_once

    while not stop.is_set():
        try:
            handled = await dispatch_once(BATCH_SIZE)
        except Exception:
            log.exception("relay_dispatch_failed")
            handled = 0
        # Back off when the queue is empty; drain hard when it is not.
        delay = POLL_INTERVAL_SECONDS if handled else IDLE_INTERVAL_SECONDS
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=delay)


async def _maintenance_loop(stop: asyncio.Event) -> None:
    from app.audit.maintenance import ensure_audit_partitions
    from app.cms.scheduler import publish_due_content
    from app.events.relay import cleanup_published
    from app.payments.maintenance import (
        reconcile_card_payments,
        release_abandoned_orders,
    )
    from app.ticketing.maintenance import expire_cart_holds, release_expired_allocations

    jobs = [
        # Frequent: an editor scheduling something for 18:00 expects it at 18:00,
        # not up to six hours later.
        PeriodicJob("publish_scheduled_content", timedelta(seconds=30), publish_due_content),
        # The card gateway has no webhook, so an order whose buyer closed the
        # tab learns nothing until somebody asks. Often, because until it is
        # asked the supporter has paid and the club cannot see the sale.
        PeriodicJob("reconcile_card_payments", timedelta(minutes=2), reconcile_card_payments),
        # And rarely, because this one gives up: it puts the stock of an
        # unpaid order back, which is the last thing that should happen in a
        # hurry.
        PeriodicJob(
            "release_abandoned_orders", timedelta(minutes=30), release_abandoned_orders
        ),
        # A ten-minute hold that lapsed at 19:00 must not still read as
        # "in a basket" at 19:05, or a club watching a sell-out sees seats it
        # has. Correctness does not depend on this — every read already treats
        # a lapsed hold as free — but the numbers on the screen do.
        PeriodicJob("expire_ticket_holds", timedelta(minutes=1), expire_cart_holds),
        PeriodicJob(
            "release_ticket_allocations", timedelta(minutes=15), release_expired_allocations
        ),
        PeriodicJob("outbox_cleanup", timedelta(hours=6), cleanup_published),
        PeriodicJob("audit_partitions", timedelta(hours=12), ensure_audit_partitions),
    ]

    while not stop.is_set():
        now = datetime.now(UTC)
        for job in jobs:
            if not job.is_due(now):
                continue
            try:
                result = await job.run()  # type: ignore[operator]
                # Quiet when there was nothing to do, so the log stays readable
                # with a job running every 30 seconds.
                if result:
                    log.info("maintenance_job_ran", job=job.name, result=result)
            except Exception:
                log.exception("maintenance_job_failed", job=job.name)
            job.last_run = now
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=15)


async def main() -> None:
    configure_logging()
    # Importing the handler module is what registers the subscriptions.
    import app.events.handlers  # noqa: F401
    from app.events.registry import all_subscriptions

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)

    subscriptions = all_subscriptions()
    log.info(
        "relay_starting",
        subscriptions=len(subscriptions),
        events=sorted({s.event_type for s in subscriptions}),
    )

    await asyncio.gather(_dispatch_loop(stop), _maintenance_loop(stop))

    from app.core.cache import cache
    from app.core.db import dispose_engines

    await cache.close()
    await dispose_engines()
    log.info("relay_stopped")


if __name__ == "__main__":
    asyncio.run(main())
