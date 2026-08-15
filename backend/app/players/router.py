"""Player routes.

Thin by construction: parse, authorise, call one service method, return. If a
handler here grows an `if` about domain state, that logic belongs in the service.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import Db, Requires, scoped_filter
from app.billing.features import Feature
from app.core.context import RequestContext
from app.core.pagination import Page, PageRequest, page_params
from app.players.schemas import (
    PlayerCreate,
    PlayerDetail,
    PlayerFilters,
    PlayerSummary,
    PlayerUpdate,
    RegistrationChange,
)
from app.players.service import PlayerService

router = APIRouter(prefix="/players", tags=["players"])

READ = "players.player.read"

# The whole module is gated on the academy entitlement: a tenant without it
# gets 402 with an upgrade hint, not 403.
ACADEMY = Feature.ACADEMY


def player_filters(
    club_id: Annotated[UUID | None, Query()] = None,
    team_id: Annotated[UUID | None, Query()] = None,
    season_id: Annotated[UUID | None, Query()] = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(max_length=80)] = None,
) -> PlayerFilters:
    return PlayerFilters(
        club_id=club_id, team_id=team_id, season_id=season_id, status=status_, q=q
    )


@router.get(
    "",
    response_model=Page[PlayerSummary],
    summary="List players",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
    },
)
async def list_players(
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(READ, feature=ACADEMY))],
    filters: Annotated[PlayerFilters, Depends(player_filters)],
    page: Annotated[PageRequest, Depends(page_params)],
) -> Page[PlayerSummary]:
    return await PlayerService(db).list_players(filters, scoped_filter(ctx, READ), page)


@router.get(
    "/{player_id}",
    response_model=PlayerDetail,
    summary="Get one player",
    responses={404: {"description": "Not found, or outside your scope"}},
)
async def get_player(
    player_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(READ, feature=ACADEMY))],
) -> PlayerDetail:
    return await PlayerService(db).get_player(player_id, scoped_filter(ctx, READ))


@router.post(
    "",
    response_model=PlayerDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Register a player",
    responses={409: {"description": "Shirt number already taken"}},
)
async def create_player(
    payload: PlayerCreate,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires("players.player.create", feature=ACADEMY))],
) -> PlayerDetail:
    return await PlayerService(db).create_player(payload, ctx)


@router.patch(
    "/{player_id}",
    response_model=PlayerDetail,
    summary="Update a player",
)
async def update_player(
    player_id: UUID,
    payload: PlayerUpdate,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires("players.player.update", feature=ACADEMY))],
) -> PlayerDetail:
    return await PlayerService(db).update_player(player_id, payload, ctx)


@router.put(
    "/{player_id}/registration",
    response_model=PlayerDetail,
    summary="Move a player to a squad",
)
async def change_registration(
    player_id: UUID,
    payload: RegistrationChange,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires("players.player.update", feature=ACADEMY))],
) -> PlayerDetail:
    return await PlayerService(db).change_registration(player_id, payload, ctx)
