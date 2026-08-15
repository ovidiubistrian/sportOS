"""The club's own numbers.

One endpoint returns the whole dashboard, because every panel on it comes from
the same window over the same table and eight round trips to build one screen
is eight chances for the totals to disagree with each other.

Everything is compared against the period immediately before it — thirty days
against the thirty before that — which is the only comparison that answers the
question a club actually has, which is "is this getting better".
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import and_, distinct, func, select

from app.analytics import service
from app.analytics.models import AnalyticsEvent
from app.api.deps import Db, Requires
from app.core.context import RequestContext

router = APIRouter(tags=["analytics"])

READ = "clubs.club.read"

# What counts as "on the site now". Long enough that somebody reading an
# article still shows, short enough to mean "now".
LIVE_WINDOW = timedelta(minutes=5)


class Metric(BaseModel):
    value: int
    previous: int
    # None when there is nothing to compare against, which is different from
    # zero change and must not be drawn as a flat arrow.
    change_percent: float | None = None


class SeriesPoint(BaseModel):
    day: str
    sessions: int
    views: int


class Count(BaseModel):
    label: str
    value: int
    # Unique visitors behind that number, where it makes sense to say.
    unique: int | None = None


class FunnelStep(BaseModel):
    label: str
    value: int
    of_total_percent: float
    from_previous_percent: float | None = None


class Overview(BaseModel):
    range: str
    since: datetime
    until: datetime

    live: int
    sessions: Metric
    visitors: Metric
    views: Metric
    signups: Metric
    conversion_percent: float
    conversion_previous_percent: float

    series: list[SeriesPoint]
    funnel: list[FunnelStep]
    sources: list[Count]
    pages: list[Count]
    devices: list[Count]
    browsers: list[Count]
    campaigns: list[Count]
    # Empty when no geography database is installed, which the dashboard reads
    # as "do not draw these panels" rather than as an error.
    countries: list[Count]
    cities: list[Count]


def _change(current: int, previous: int) -> float | None:
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


def _scope(club_id: UUID | None, ctx: RequestContext, since: datetime, until: datetime):
    conditions = [
        AnalyticsEvent.tenant_id == ctx.tenant,
        AnalyticsEvent.occurred_at >= since,
        AnalyticsEvent.occurred_at < until,
    ]
    if club_id is not None:
        conditions.append(AnalyticsEvent.club_id == club_id)
    return and_(*conditions)


@router.get("/analytics/overview", response_model=Overview, summary="Website analytics")
async def overview(
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(READ))],
    club_id: Annotated[UUID | None, Query()] = None,
    range_key: Annotated[str, Query(alias="range")] = "30d",
) -> Overview:
    since, until, span = service.window(range_key)
    before = since - span

    now_scope = _scope(club_id, ctx, since, until)
    prev_scope = _scope(club_id, ctx, before, since)

    async def totals(scope) -> tuple[int, int, int, int]:
        row = (
            await db.execute(
                select(
                    func.count(distinct(AnalyticsEvent.session_id)),
                    func.count(distinct(AnalyticsEvent.visitor_hash)),
                    func.count().filter(AnalyticsEvent.kind == "PAGEVIEW"),
                    func.count().filter(
                        AnalyticsEvent.kind.in_(("NEWSLETTER_SIGNUP", "ACCOUNT_SIGNUP"))
                    ),
                ).where(scope)
            )
        ).one()
        return int(row[0]), int(row[1]), int(row[2]), int(row[3])

    sessions, visitors, views, signups = await totals(now_scope)
    p_sessions, p_visitors, p_views, p_signups = await totals(prev_scope)

    live = int(
        await db.scalar(
            select(func.count(distinct(AnalyticsEvent.session_id))).where(
                _scope(club_id, ctx, until - LIVE_WINDOW, until + timedelta(minutes=1))
            )
        )
        or 0
    )

    # One row per day, sessions and views side by side — the chart the club
    # looks at first.
    day = func.date_trunc("day", AnalyticsEvent.occurred_at)
    series_rows = await db.execute(
        select(
            day.label("day"),
            func.count(distinct(AnalyticsEvent.session_id)),
            func.count().filter(AnalyticsEvent.kind == "PAGEVIEW"),
        )
        .where(now_scope)
        .group_by(day)
        .order_by(day)
    )
    series = [
        SeriesPoint(day=row[0].date().isoformat(), sessions=int(row[1]), views=int(row[2]))
        for row in series_rows
    ]

    async def top(column, limit: int = 8, with_unique: bool = False) -> list[Count]:
        stmt = (
            select(
                column,
                func.count().label("hits"),
                func.count(distinct(AnalyticsEvent.visitor_hash)),
            )
            .where(and_(now_scope, column.isnot(None)))
            .group_by(column)
            .order_by(func.count().desc())
            .limit(limit)
        )
        return [
            Count(
                label=str(row[0]),
                value=int(row[1]),
                unique=int(row[2]) if with_unique else None,
            )
            for row in await db.execute(stmt)
        ]

    async def step(kinds: tuple[str, ...]) -> int:
        return int(
            await db.scalar(
                select(func.count(distinct(AnalyticsEvent.session_id))).where(
                    and_(now_scope, AnalyticsEvent.kind.in_(kinds))
                )
            )
            or 0
        )

    # Sessions rather than events at every step: a funnel counting events says
    # 900 basket adds from 300 people and reads as a 300% conversion.
    shop = await step(("SHOP_VIEW",))
    checkout = await step(("CHECKOUT",))
    orders = await step(("ORDER",))

    def pct(value: int, of: int) -> float:
        return round(value / of * 100, 1) if of else 0.0

    funnel = [
        FunnelStep(label="visits", value=sessions, of_total_percent=100.0),
        FunnelStep(
            label="shop",
            value=shop,
            of_total_percent=pct(shop, sessions),
            from_previous_percent=pct(shop, sessions),
        ),
        FunnelStep(
            label="checkout",
            value=checkout,
            of_total_percent=pct(checkout, sessions),
            from_previous_percent=pct(checkout, shop),
        ),
        FunnelStep(
            label="orders",
            value=orders,
            of_total_percent=pct(orders, sessions),
            from_previous_percent=pct(orders, checkout),
        ),
    ]

    return Overview(
        range=range_key,
        since=since,
        until=until,
        live=live,
        sessions=Metric(
            value=sessions, previous=p_sessions, change_percent=_change(sessions, p_sessions)
        ),
        visitors=Metric(
            value=visitors, previous=p_visitors, change_percent=_change(visitors, p_visitors)
        ),
        views=Metric(value=views, previous=p_views, change_percent=_change(views, p_views)),
        signups=Metric(
            value=signups, previous=p_signups, change_percent=_change(signups, p_signups)
        ),
        conversion_percent=pct(signups, sessions),
        conversion_previous_percent=pct(p_signups, p_sessions),
        series=series,
        funnel=funnel,
        sources=await top(AnalyticsEvent.referrer_host),
        pages=await top(AnalyticsEvent.path, limit=10, with_unique=True),
        devices=await top(AnalyticsEvent.device, limit=4),
        browsers=await top(AnalyticsEvent.browser, limit=6),
        campaigns=await top(AnalyticsEvent.utm_campaign, limit=6),
        countries=await top(AnalyticsEvent.country, limit=8, with_unique=True),
        cities=await top(AnalyticsEvent.city, limit=8, with_unique=True),
    )
