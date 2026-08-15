"""The sports the platform knows about.

Reference data, like the locale registry: read by the admin so a club can pick
what it plays, and by nothing else. Unauthenticated would be fine — there is
nothing here a competitor could not read off the marketing site — but it sits
behind an ordinary session because only signed-in screens ask.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import Requires
from app.core.context import RequestContext
from app.sports.registry import SPORTS

router = APIRouter(tags=["sports"])


class SportOut(BaseModel):
    key: str
    name: str
    scoring_unit: str
    draws_possible: bool
    period_count: int
    period_minutes: int | None
    tracks_minute: bool
    positions: list[str]
    event_kinds: list[str]
    # Whether a league feed can fill this sport's fixtures in, or whether the
    # club will be entering them by hand.
    has_provider: bool


@router.get("/sports", response_model=list[SportOut], summary="Sports the platform supports")
async def list_sports(
    _: Annotated[RequestContext, Depends(Requires("clubs.club.read"))],
) -> list[SportOut]:
    return [
        SportOut(
            key=sport.key,
            name=sport.name,
            scoring_unit=sport.scoring_unit,
            draws_possible=sport.draws_possible,
            period_count=sport.period_count,
            period_minutes=sport.period_minutes,
            tracks_minute=sport.tracks_minute,
            positions=list(sport.positions),
            event_kinds=list(sport.event_kinds),
            has_provider=sport.provider is not None,
        )
        for sport in SPORTS
    ]
