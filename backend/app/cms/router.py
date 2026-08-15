"""Content management routes (staff-facing)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from app.api.deps import Db, Requires
from app.audit.service import AuditService
from app.billing.features import Feature
from app.cms.models import ContentItem, ContentTranslation
from app.cms.schemas import (
    ContentCreate,
    ContentDetail,
    ContentSummary,
    ContentTransition,
    TranslationDetail,
    TranslationInput,
    TranslationSummary,
)
from app.cms.service import ContentService
from app.core.context import RequestContext
from app.core.errors import NotFound
from app.core.pagination import Page, PageMeta, PageRequest, count_for, page_params
from app.media import storage
from app.media.models import MediaAsset

router = APIRouter(prefix="/content", tags=["cms"])

CMS = Feature.CMS
READ = "cms.content.read"
WRITE = "cms.content.write"
PUBLISH = "cms.content.publish"


async def _cover_urls(db: Db, items: list[ContentItem]) -> dict[UUID, str]:
    """Cover URLs for a page of articles, in one query rather than one each."""
    ids = {item.cover_media_id for item in items if item.cover_media_id}
    if not ids:
        return {}
    assets = await db.scalars(select(MediaAsset).where(MediaAsset.id.in_(ids)))
    return {asset.id: storage.public_url(asset.storage_key) for asset in assets}


def _summary(
    item: ContentItem,
    translations: list[ContentTranslation],
    covers: dict[UUID, str] | None = None,
) -> ContentSummary:
    locales = [
        TranslationSummary(
            locale=t.locale,
            title=t.title,
            slug=t.slug,
            status=t.status,
            # "Complete" means publishable, not merely present: an empty body
            # in a second language is a stub, and the editor needs to see that.
            is_complete=bool(t.title.strip() and t.body),
        )
        for t in translations
    ]
    return ContentSummary(
        id=item.id,
        club_id=item.club_id,
        kind=item.kind,
        article_type=item.article_type,
        status=item.status,
        published_at=item.published_at,
        scheduled_for=item.scheduled_for,
        is_pinned=item.is_pinned,
        cover_media_id=item.cover_media_id,
        cover_url=(covers or {}).get(item.cover_media_id) if item.cover_media_id else None,
        title=translations[0].title if translations else "(untitled)",
        locales=locales,
        updated_at=item.updated_at,
    )


@router.get("", response_model=Page[ContentSummary], summary="List content")
async def list_content(
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(READ, feature=CMS))],
    page: Annotated[PageRequest, Depends(page_params)],
    club_id: Annotated[UUID | None, Query()] = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
    article_type: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
) -> Page[ContentSummary]:
    stmt = select(ContentItem).where(ContentItem.tenant_id == ctx.tenant)
    if club_id:
        stmt = stmt.where(ContentItem.club_id == club_id)
    if status_:
        stmt = stmt.where(ContentItem.status == status_)
    if article_type:
        stmt = stmt.where(ContentItem.article_type == article_type)
    if q:
        stmt = stmt.where(
            ContentItem.id.in_(
                select(ContentTranslation.content_item_id).where(
                    ContentTranslation.tenant_id == ctx.tenant,
                    ContentTranslation.title.ilike(f"%{q.strip()}%"),
                )
            )
        )

    total, is_estimate = (None, False)
    if page.with_total:
        total, is_estimate = await count_for(db, stmt)

    items = list(
        await db.scalars(
            stmt.order_by(
                ContentItem.is_pinned.desc(),
                func.coalesce(
                    ContentItem.published_at, ContentItem.scheduled_for, ContentItem.updated_at
                ).desc(),
            )
            .limit(page.limit)
            .offset(page.offset)
        )
    )

    # One query for every item's translations rather than one per item.
    by_item: dict[UUID, list[ContentTranslation]] = {item.id: [] for item in items}
    if items:
        for translation in await db.scalars(
            select(ContentTranslation)
            .where(ContentTranslation.content_item_id.in_(by_item))
            .order_by(ContentTranslation.locale)
        ):
            by_item[translation.content_item_id].append(translation)

    covers = await _cover_urls(db, items)
    return Page[ContentSummary](
        data=[_summary(item, by_item[item.id], covers) for item in items],
        page=PageMeta(
            limit=page.limit,
            offset=page.offset,
            total=total,
            total_is_estimate=is_estimate,
            has_more=len(items) == page.limit,
        ),
    )


async def _detail(db: Db, service: ContentService, item: ContentItem) -> ContentDetail:
    translations = await service.translations_for(item.id)
    summary = _summary(item, translations, await _cover_urls(db, [item]))
    return ContentDetail(
        **summary.model_dump(),
        category_id=item.category_id,
        translations=[TranslationDetail.model_validate(t) for t in translations],
    )


class ContentItemUpdate(BaseModel):
    """Item-level fields — the ones that are not per-language."""

    model_config = ConfigDict(extra="forbid")

    cover_media_id: UUID | None = None
    is_pinned: bool | None = None
    category_id: UUID | None = None


@router.patch("/{item_id}", response_model=ContentDetail, summary="Update an article")
async def update_content(
    item_id: UUID,
    payload: ContentItemUpdate,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(WRITE, feature=CMS))],
) -> ContentDetail:
    """The picture and the pin.

    Separate from the translation endpoint because neither is per-language: a
    photograph of a signing is the same photograph in Romanian, and an article
    pinned in one language and not the other is not a state worth modelling.
    """
    service = ContentService(db)
    item = await service.get_item(ctx, item_id)

    changes = payload.model_dump(exclude_unset=True)
    if changes.get("cover_media_id") is not None:
        asset = await db.scalar(
            select(MediaAsset).where(
                MediaAsset.id == changes["cover_media_id"],
                MediaAsset.tenant_id == ctx.tenant,
            )
        )
        if asset is None:
            raise NotFound(object_type="media_asset", object_id=str(changes["cover_media_id"]))

    before = {field: getattr(item, field) for field in changes}
    for field, value in changes.items():
        setattr(item, field, value)

    AuditService(db).record(
        ctx,
        action="cms.content.update",
        object_type="content_item",
        object_id=item.id,
        club_id=item.club_id,
        before=before,
        after=changes,
    )
    await db.flush()
    return await _detail(db, service, item)


@router.get("/{item_id}", response_model=ContentDetail, summary="Get one article")
async def get_content(
    item_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(READ, feature=CMS))],
) -> ContentDetail:
    service = ContentService(db)
    return await _detail(db, service, await service.get_item(ctx, item_id))


@router.post(
    "",
    response_model=ContentDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create an article",
)
async def create_content(
    payload: ContentCreate,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(WRITE, feature=CMS))],
) -> ContentDetail:
    service = ContentService(db)
    item = await service.create(
        ctx,
        club_id=payload.club_id,
        category_id=payload.category_id,
        article_type=payload.article_type,
        cover_media_id=payload.cover_media_id,
        locale=payload.translation.locale,
        title=payload.translation.title,
        body=payload.translation.body,
        excerpt=payload.translation.excerpt,
        slug=payload.translation.slug,
    )
    return await _detail(db, service, item)


@router.put(
    "/{item_id}/translations/{locale}",
    response_model=ContentDetail,
    summary="Create or replace one language",
)
async def upsert_translation(
    item_id: UUID,
    locale: str,
    payload: TranslationInput,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(WRITE, feature=CMS))],
) -> ContentDetail:
    service = ContentService(db)
    item = await service.get_item(ctx, item_id)
    await service.upsert_translation(
        ctx,
        item,
        locale=locale.lower(),
        title=payload.title,
        body=payload.body,
        excerpt=payload.excerpt,
        slug=payload.slug,
        seo_title=payload.seo_title,
        seo_description=payload.seo_description,
        status=payload.status,
    )
    return await _detail(db, service, item)


@router.post(
    "/{item_id}/status",
    response_model=ContentDetail,
    summary="Publish, schedule, archive or return to draft",
)
async def transition_content(
    item_id: UUID,
    payload: ContentTransition,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(PUBLISH, feature=CMS))],
) -> ContentDetail:
    service = ContentService(db)
    item = await service.get_item(ctx, item_id)
    await service.transition(ctx, item, payload.status, scheduled_for=payload.scheduled_for)
    return await _detail(db, service, item)


@router.delete(
    "/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an article",
)
async def delete_content(
    item_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(WRITE, feature=CMS))],
) -> None:
    service = ContentService(db)
    await service.delete(ctx, await service.get_item(ctx, item_id))
