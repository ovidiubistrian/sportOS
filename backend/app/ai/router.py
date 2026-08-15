"""Writing assistant routes.

The assistant proposes; the editor disposes. No endpoint here writes to an
article — a suggestion is returned, shown side by side, and saved only if the
editor accepts it through the normal content-update route.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.ai.provider import get_provider
from app.ai.service import WritingAssistant
from app.api.deps import Db, Requires
from app.billing.features import Feature
from app.cms.article_types import BY_KEY, DEFAULT_TYPE, TYPES
from app.cms.service import ContentService
from app.core.context import RequestContext
from app.core.errors import ValidationFailed

router = APIRouter(prefix="/ai", tags=["ai"])

ASSIST = Feature.AI_ASSIST


class AssistRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_item_id: UUID | None = None
    locale: str = Field(min_length=2, max_length=10)
    # Sent from the editor rather than read from the database, so the assistant
    # works on what the editor is looking at right now — including unsaved edits.
    title: str = Field(min_length=1, max_length=240)
    blocks: list[dict[str, Any]] = Field(default_factory=list)


class PolishResponse(BaseModel):
    usage_id: UUID
    blocks: list[dict[str, Any]]
    summary_of_changes: str
    requests_used: int
    duration_ms: int


class HeadlineResponse(BaseModel):
    usage_id: UUID
    headlines: list[str]
    requests_used: int
    duration_ms: int


class OutcomeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool


class ArticleTypeOut(BaseModel):
    key: str
    name: str
    description: str
    skeleton: list[dict[str, Any]]


class AssistantStatus(BaseModel):
    available: bool
    reason: str | None = None
    requests_used: int
    requests_limit: int | None
    article_types: list[ArticleTypeOut]


async def _context_for(
    db: Db, ctx: RequestContext, payload: AssistRequest
) -> tuple[str, UUID | None]:
    """Resolve the article's type and club, when it is an existing article."""
    if payload.content_item_id is None:
        return DEFAULT_TYPE, None
    # Raises 404 for an article in another tenant, so the assistant cannot be
    # used to probe for the existence of other clubs' drafts.
    item = await ContentService(db).get_item(ctx, payload.content_item_id)
    return item.article_type, item.club_id


@router.get("/assistant", response_model=AssistantStatus, summary="Assistant status")
async def assistant_status(
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires("cms.content.read"))],
) -> AssistantStatus:
    """What the editor needs to decide whether to show the assistant at all."""
    entitlements = ctx.entitlements
    entitled = entitlements is not None and entitlements.enabled(ASSIST)
    configured = get_provider().is_configured

    used = await WritingAssistant(db).usage_this_period(ctx.tenant)
    limit = entitlements.limit(Feature.AI_REQUESTS_PER_MONTH) if entitlements else 0

    reason = None
    if not entitled:
        reason = "The writing assistant is not included in your plan."
    elif not configured:
        reason = "The writing assistant is not configured on this platform."
    elif limit is not None and used >= limit:
        reason = f"You have used all {limit} assistant requests this month."

    return AssistantStatus(
        available=entitled and configured and (limit is None or used < limit),
        reason=reason,
        requests_used=used,
        requests_limit=limit,
        article_types=[
            ArticleTypeOut(
                key=t.key, name=t.name, description=t.description, skeleton=list(t.skeleton)
            )
            for t in TYPES
        ],
    )


@router.post(
    "/polish",
    response_model=PolishResponse,
    summary="Suggest an improved version of an article",
    responses={
        402: {"description": "Not included in your plan"},
        409: {"description": "Monthly request limit reached"},
        422: {"description": "The assistant declined, or the draft is unusable"},
        503: {"description": "The assistant is unavailable"},
    },
)
async def polish(
    payload: AssistRequest,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires("cms.content.write", feature=ASSIST))],
) -> PolishResponse:
    article_type, club_id = await _context_for(db, ctx, payload)
    result = await WritingAssistant(db).polish(
        ctx,
        title=payload.title,
        blocks=payload.blocks,
        locale=payload.locale,
        article_type=article_type,
        object_id=payload.content_item_id,
        club_id=club_id,
    )
    return PolishResponse(**result)


@router.post(
    "/headlines",
    response_model=HeadlineResponse,
    summary="Suggest alternative headlines",
)
async def headlines(
    payload: AssistRequest,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires("cms.content.write", feature=ASSIST))],
) -> HeadlineResponse:
    article_type, club_id = await _context_for(db, ctx, payload)
    result = await WritingAssistant(db).headlines(
        ctx,
        title=payload.title,
        blocks=payload.blocks,
        locale=payload.locale,
        article_type=article_type,
        object_id=payload.content_item_id,
        club_id=club_id,
    )
    return HeadlineResponse(**result)


@router.post(
    "/usage/{usage_id}/outcome",
    status_code=204,
    summary="Record whether a suggestion was accepted",
)
async def record_outcome(
    usage_id: UUID,
    payload: OutcomeRequest,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires("cms.content.write", feature=ASSIST))],
) -> None:
    """Tells us whether the assistant is actually useful, rather than just used."""
    await WritingAssistant(db).mark_outcome(usage_id, accepted=payload.accepted)


@router.get(
    "/article-types/{key}/skeleton",
    response_model=ArticleTypeOut,
    summary="Starter structure for an article type",
)
async def article_skeleton(
    key: str,
    ctx: Annotated[RequestContext, Depends(Requires("cms.content.write"))],
) -> ArticleTypeOut:
    spec = BY_KEY.get(key.upper())
    if spec is None:
        raise ValidationFailed(f"Unknown article type {key!r}.", known=sorted(BY_KEY))
    return ArticleTypeOut(
        key=spec.key,
        name=spec.name,
        description=spec.description,
        skeleton=list(spec.skeleton),
    )
