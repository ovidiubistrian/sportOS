"""Returning lapsed baskets to sale, and expiring stale allocations.

Both jobs run in the relay's maintenance loop, across every tenant, so they
open a `platform_session` with RLS off rather than a tenant-scoped one.

Neither is load-bearing for correctness. A seat whose hold has lapsed is
already treated as free by every read and write path — see `inventory.is_free`
— so nothing is lost if these do not run for an hour. What they buy is honest
*reporting*: without them, "seats held in baskets" grows forever and a club
looking at its own occupancy sees a sell-out that is not there.

That is deliberate. A sweep the correctness of the system depends on is a sweep
that takes the system down with it when it stops.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy import select, update

from app.core.db import platform_session
from app.ticketing.event_models import Allocation, EventSeatInventory
from app.ticketing.inventory import expire_holds

log = structlog.get_logger(__name__)


async def expire_cart_holds() -> dict[str, int]:
    """Put seats from abandoned baskets back on sale."""
    async with platform_session(
        reason="maintenance: return lapsed cart holds to sale", routine=True
    ) as session:
        released = await expire_holds(session)
        await session.commit()

    if released:
        log.info("ticket_holds_expired", seats=released)
    return {"released": released}


async def release_expired_allocations() -> dict[str, int]:
    """Return unclaimed soft allocations to public sale once they lapse.

    Soft allocations only. A hard hold is a closed stand or a broken seat and
    must never quietly reopen because a date passed — somebody has to decide
    that the scaffolding is down.
    """
    now = datetime.now(UTC)
    released = 0
    lapsed = 0

    async with platform_session(
        reason="maintenance: release expired soft allocations", routine=True
    ) as session:
        allocations = list(
            await session.scalars(
                select(Allocation).where(
                    Allocation.kind == "SOFT_ALLOCATION",
                    Allocation.expires_at.is_not(None),
                    Allocation.expires_at <= now,
                    Allocation.released_at.is_(None),
                )
            )
        )
        for allocation in allocations:
            result = await session.execute(
                update(EventSeatInventory)
                .where(
                    EventSeatInventory.allocation_id == allocation.id,
                    EventSeatInventory.state == "SOFT_ALLOCATED",
                )
                .values(state="AVAILABLE", allocation_id=None)
            )
            released += int(result.rowcount or 0)
            allocation.released_at = now
            lapsed += 1
        await session.commit()

    if lapsed:
        log.info("ticket_allocations_released", allocations=lapsed, seats=released)
    return {"allocations": lapsed, "seats": released}
