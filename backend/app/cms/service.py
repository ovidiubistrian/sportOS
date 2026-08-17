"""Content service: the publishing state machine and locale resolution."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import AuditService
from app.cms.article_types import BY_KEY, DEFAULT_TYPE
from app.cms.blocks import plain_text, validate_body
from app.cms.models import ContentItem, ContentTranslation
from app.core.context import RequestContext
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.events.base import ContentPublished
from app.events.publisher import publish

log = structlog.get_logger(__name__)

# status -> what it may become. Written out rather than inferred so an illegal
# transition is a data-model question, not a scattered set of `if`s.
TRANSITIONS: dict[str, frozenset[str]] = {
    "DRAFT": frozenset({"IN_REVIEW", "SCHEDULED", "PUBLISHED", "ARCHIVED"}),
    "IN_REVIEW": frozenset({"DRAFT", "SCHEDULED", "PUBLISHED", "ARCHIVED"}),
    "SCHEDULED": frozenset({"DRAFT", "PUBLISHED", "ARCHIVED"}),
    "PUBLISHED": frozenset({"ARCHIVED", "DRAFT"}),
    "ARCHIVED": frozenset({"DRAFT", "PUBLISHED"}),
}

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


# `content_translation.seo_description`. The column, not the advice: a search
# engine shows about a hundred and sixty characters of it.
SEO_DESCRIPTION_MAX = 400


def _meta_description(excerpt: str | None) -> str | None:
    """The summary, cut to what the column holds.

    The excerpt is `text` and the schema lets an editor write six hundred
    characters of it; the meta description beside it is `varchar(400)`. Taking
    one as the other worked until somebody pasted a paragraph, and then the
    insert failed on the database rather than on any validation — a 500 on
    saving an article, with the length of a field nobody had typed into.

    Cut on a word, the way an excerpt derived from the body already is.
    """
    if not excerpt:
        return None
    text = excerpt.strip()
    if len(text) <= SEO_DESCRIPTION_MAX:
        return text or None
    return text[: SEO_DESCRIPTION_MAX - 1].rsplit(" ", 1)[0] + "…"


def slugify(value: str, *, max_length: int = 80) -> str:
    """A URL slug that survives diacritics.

    `Echipa noastră în Ștefănești` must become `echipa-noastra-in-stefanesti`,
    not a string of stripped characters — the launch locales are Romanian and
    German, so this is the common case rather than an edge one.
    """
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_only = decomposed.encode("ascii", "ignore").decode()
    slug = _SLUG_STRIP.sub("-", ascii_only.lower()).strip("-")
    if len(slug) > max_length:
        slug = slug[:max_length].rsplit("-", 1)[0]
    return slug or "untitled"


class ContentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- queries ---------------------------------------------------------

    async def get_item(self, ctx: RequestContext, item_id: UUID) -> ContentItem:
        item = await self.session.scalar(
            select(ContentItem).where(
                ContentItem.id == item_id, ContentItem.tenant_id == ctx.tenant
            )
        )
        if item is None:
            raise NotFound(object_type="content_item", object_id=str(item_id))
        return item

    async def translations_for(self, item_id: UUID) -> list[ContentTranslation]:
        return list(
            await self.session.scalars(
                select(ContentTranslation)
                .where(ContentTranslation.content_item_id == item_id)
                .order_by(ContentTranslation.locale)
            )
        )

    # --- commands --------------------------------------------------------

    async def create(
        self,
        ctx: RequestContext,
        *,
        club_id: UUID,
        locale: str,
        title: str,
        article_type: str = DEFAULT_TYPE,
        body: list[dict] | None = None,
        excerpt: str | None = None,
        slug: str | None = None,
        category_id: UUID | None = None,
        cover_media_id: UUID | None = None,
    ) -> ContentItem:
        if article_type not in BY_KEY:
            raise ValidationFailed(
                f"Unknown article type {article_type!r}.", known=sorted(BY_KEY)
            )
        item = ContentItem(
            tenant_id=ctx.tenant,
            club_id=club_id,
            category_id=category_id,
            kind="ARTICLE",
            article_type=article_type,
            status="DRAFT",
            cover_media_id=cover_media_id,
            created_by=ctx.actor_id,
        )
        self.session.add(item)
        await self.session.flush()

        await self.upsert_translation(
            ctx,
            item,
            locale=locale,
            title=title,
            body=body,
            excerpt=excerpt,
            slug=slug,
        )

        AuditService(self.session).record(
            ctx,
            action="cms.content.create",
            object_type="content_item",
            object_id=item.id,
            after={
                "status": item.status,
                "kind": item.kind,
                "article_type": item.article_type,
            },
            club_id=club_id,
        )
        return item

    async def upsert_translation(
        self,
        ctx: RequestContext,
        item: ContentItem,
        *,
        locale: str,
        title: str,
        body: list[dict] | None = None,
        excerpt: str | None = None,
        slug: str | None = None,
        seo_title: str | None = None,
        seo_description: str | None = None,
        status: str | None = None,
    ) -> ContentTranslation:
        clean_body = validate_body(body)

        translation = await self.session.scalar(
            select(ContentTranslation).where(
                ContentTranslation.content_item_id == item.id,
                ContentTranslation.locale == locale,
            )
        )
        if translation is None:
            translation = ContentTranslation(
                tenant_id=ctx.tenant,
                content_item_id=item.id,
                club_id=item.club_id,
                locale=locale,
            )
            self.session.add(translation)

        translation.title = title.strip()
        translation.slug = await self._unique_slug(
            item, locale, slug or slugify(title), exclude_id=translation.id
        )
        translation.excerpt = (excerpt or plain_text(clean_body, limit=200)) or None
        translation.body = clean_body
        translation.seo_title = seo_title
        translation.seo_description = seo_description or _meta_description(translation.excerpt)
        translation.status = status or translation.status or "DRAFT"
        translation.translated_by = ctx.actor_id

        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise Conflict("That slug is already used by another article.") from exc
        return translation

    async def _unique_slug(
        self, item: ContentItem, locale: str, base: str, *, exclude_id: UUID | None
    ) -> str:
        """Append a suffix rather than failing: two match reports on the same
        day legitimately share a title, and an editor should not have to care."""
        candidate = slugify(base)
        for attempt in range(50):
            value = candidate if attempt == 0 else f"{candidate}-{attempt + 1}"
            query = select(ContentTranslation.id).where(
                ContentTranslation.club_id == item.club_id,
                ContentTranslation.locale == locale,
                ContentTranslation.slug == value,
            )
            if exclude_id is not None:
                query = query.where(ContentTranslation.id != exclude_id)
            if await self.session.scalar(query) is None:
                return value
        raise ValidationFailed("Could not derive a unique slug; please set one.")

    async def transition(
        self,
        ctx: RequestContext,
        item: ContentItem,
        target: str,
        *,
        scheduled_for: datetime | None = None,
    ) -> ContentItem:
        if target not in TRANSITIONS:
            raise ValidationFailed(f"Unknown status {target!r}.")
        if target not in TRANSITIONS[item.status]:
            raise Conflict(
                f"An article that is {item.status.lower()} cannot become {target.lower()}.",
                from_status=item.status,
                to_status=target,
            )

        if target in ("PUBLISHED", "SCHEDULED") and not await self._has_ready_translation(item):
            raise ValidationFailed(
                "Add a title and body in at least one language before publishing.",
                fields=[{"field": "translations", "code": "NO_READY_TRANSLATION"}],
            )

        before = {"status": item.status}
        now = datetime.now(UTC)

        if target == "SCHEDULED":
            if scheduled_for is None:
                raise ValidationFailed("A scheduled article needs a date and time.")
            if scheduled_for <= now:
                raise ValidationFailed(
                    "That time is in the past. Publish it now instead.",
                    fields=[{"field": "scheduled_for", "code": "IN_THE_PAST"}],
                )
            item.scheduled_for = scheduled_for
        elif target == "PUBLISHED":
            item.published_at = item.published_at or now
            item.scheduled_for = None

        item.status = target

        AuditService(self.session).record(
            ctx,
            action=f"cms.content.{target.lower()}",
            object_type="content_item",
            object_id=item.id,
            before=before,
            after={"status": target},
            club_id=item.club_id,
        )
        if target == "PUBLISHED":
            publish(self.session, ContentPublished.of(item.id, tenant_id=ctx.tenant))

        await self.session.flush()
        log.info("content_transitioned", item_id=str(item.id), status=target)
        return item

    async def _has_ready_translation(self, item: ContentItem) -> bool:
        for translation in await self.translations_for(item.id):
            if translation.title.strip() and translation.body:
                return True
        return False

    async def delete(self, ctx: RequestContext, item: ContentItem) -> None:
        AuditService(self.session).record(
            ctx,
            action="cms.content.delete",
            object_type="content_item",
            object_id=item.id,
            before={"status": item.status},
            club_id=item.club_id,
        )
        await self.session.delete(item)


def pick_translation(
    translations: list[Any], requested: str | None, default_locale: str
) -> Any | None:
    """Choose which language to serve.

    Exact match, then the club's default, then whatever exists. Not every
    article is translated into every supported language, and a missing German
    version must show the Romanian original rather than a 404.
    """
    if not translations:
        return None
    by_locale = {t.locale: t for t in translations}

    for candidate in (requested, (requested or "").split("-")[0], default_locale):
        if candidate and candidate in by_locale:
            return by_locale[candidate]

    # Language-only match, e.g. requested "de-AT" against a stored "de".
    if requested:
        prefix = requested.split("-")[0]
        for locale, translation in by_locale.items():
            if locale.split("-")[0] == prefix:
                return translation

    return translations[0]
