from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.cms.article_types import ARTICLE_TYPES, DEFAULT_TYPE
from app.cms.blocks import MAX_BLOCKS
from app.cms.models import CONTENT_STATUSES


class TranslationSummary(BaseModel):
    locale: str
    title: str
    slug: str
    status: str
    is_complete: bool


class ContentSummary(BaseModel):
    id: UUID
    club_id: UUID
    kind: str
    article_type: str
    status: str
    published_at: datetime | None
    scheduled_for: datetime | None
    is_pinned: bool
    cover_media_id: UUID | None = None
    cover_url: str | None = None
    title: str
    locales: list[TranslationSummary]
    updated_at: datetime


class TranslationDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    locale: str
    title: str
    slug: str
    excerpt: str | None
    body: list[dict[str, Any]]
    seo_title: str | None
    seo_description: str | None
    status: str


class ContentDetail(ContentSummary):
    translations: list[TranslationDetail]
    category_id: UUID | None


class TranslationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locale: str = Field(min_length=2, max_length=10)
    title: str = Field(min_length=1, max_length=240)
    slug: str | None = Field(default=None, max_length=240)
    excerpt: str | None = Field(default=None, max_length=600)
    body: list[dict[str, Any]] = Field(default_factory=list, max_length=MAX_BLOCKS)
    seo_title: str | None = Field(default=None, max_length=240)
    seo_description: str | None = Field(default=None, max_length=400)
    status: str | None = None

    @field_validator("locale")
    @classmethod
    def _normalise_locale(cls, value: str) -> str:
        return value.strip().lower()


class ContentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    club_id: UUID
    category_id: UUID | None = None
    article_type: str = DEFAULT_TYPE
    cover_media_id: UUID | None = None
    translation: TranslationInput

    @field_validator("article_type")
    @classmethod
    def _known_type(cls, value: str) -> str:
        if value not in ARTICLE_TYPES:
            raise ValueError(f"must be one of {', '.join(ARTICLE_TYPES)}")
        return value


class ContentTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    scheduled_for: datetime | None = None

    @field_validator("status")
    @classmethod
    def _known_status(cls, value: str) -> str:
        if value not in CONTENT_STATUSES:
            raise ValueError(f"must be one of {', '.join(CONTENT_STATUSES)}")
        return value


# --- public shapes ---------------------------------------------------------


class PublicArticleSummary(BaseModel):
    id: UUID
    slug: str
    locale: str
    title: str
    excerpt: str | None
    published_at: datetime | None
    is_pinned: bool
    category: str | None = None
    cover_url: str | None = None
    # SIGNING, DEPARTURE, MATCH_REPORT… The club feed badges by this, so a
    # supporter can tell a transfer from a match report before reading either.
    article_type: str = "ANNOUNCEMENT"


class PublicArticle(PublicArticleSummary):
    body: list[dict[str, Any]]
    seo_title: str | None
    seo_description: str | None
    # Set when the requested language was unavailable and another was served, so
    # the page can say so rather than silently showing an unexpected language.
    served_locale_fallback: bool = False
