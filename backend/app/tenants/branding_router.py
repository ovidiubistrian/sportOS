"""Club design settings.

The club chooses a template and up to three colours. That is the entire surface
— no custom CSS, no per-component overrides. The constraint is the product:
it is what lets every tenant's site be recognisably the same software, and what
stops a brand colour making a club's own checkout unreadable.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from app.api.deps import Db, Requires
from app.audit.service import AuditService
from app.core.context import RequestContext
from app.core.errors import NotFound, ValidationFailed
from app.events.base import ClubBrandingChanged
from app.events.publisher import publish
from app.media import storage
from app.media.models import MediaAsset
from app.tenants.branding_models import COLOR_MODES, SITE_TEMPLATES, ClubBranding
from app.tenants.colors import (
    AA_NON_TEXT,
    AA_NORMAL_TEXT,
    InvalidColor,
    assess,
    build_palette,
    normalise,
)
from app.tenants.models import Club

router = APIRouter(tags=["branding"])


class ColorCheck(BaseModel):
    """What the picker shows next to each colour."""

    color: str
    on_color: str
    text_variant: str
    was_adjusted: bool
    contrast_on_white: float
    meets_aa_as_text: bool
    meets_aa_as_surface: bool
    advice: str | None = None


class BrandingOut(BaseModel):
    club_id: UUID
    template: str
    color_mode: str
    color_primary: str
    color_secondary: str | None
    color_accent: str | None
    tagline: str | None
    social: dict
    # Resolved from the asset id at read time, so a deleted image degrades to
    # no crest rather than to a broken URL on the club's home page.
    crest_url: str | None = None
    hero_url: str | None = None
    crest_media_id: UUID | None = None
    hero_media_id: UUID | None = None
    announcement_text: str | None = None
    announcement_is_active: bool = False
    tickets_url: str | None = None
    tickets_label: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    address: str | None = None
    legal_line: str | None = None
    sponsors_title: str | None = None
    # Read back with each logo resolved to a URL, and any sponsor whose image
    # has since been deleted simply carries no logo.
    sponsors: list[dict] = Field(default_factory=list)
    display_name: str | None = None
    short_name: str | None = None
    founded_year: int | None = None
    palette: dict[str, str]
    checks: dict[str, ColorCheck]
    available_templates: list[str] = Field(default_factory=lambda: list(SITE_TEMPLATES))
    available_color_modes: list[str] = Field(default_factory=lambda: list(COLOR_MODES))


class Sponsor(BaseModel):
    """A name, a logo and somewhere to click.

    The logo is an asset id rather than a URL for the same reason the crest is:
    a club deleting an image should lose a logo, not gain a broken one.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    url: str | None = Field(default=None, max_length=500)
    media_id: UUID | None = None


class BrandingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: str | None = None
    color_mode: str | None = None
    color_primary: str | None = None
    color_secondary: str | None = None
    color_accent: str | None = None
    tagline: str | None = Field(default=None, max_length=160)
    social: dict[str, str] | None = None
    crest_media_id: UUID | None = None
    hero_media_id: UUID | None = None
    announcement_text: str | None = Field(default=None, max_length=300)
    announcement_is_active: bool | None = None
    tickets_url: str | None = Field(default=None, max_length=500)
    tickets_label: str | None = Field(default=None, max_length=48)
    contact_email: str | None = Field(default=None, max_length=320)
    contact_phone: str | None = Field(default=None, max_length=32)
    address: str | None = Field(default=None, max_length=400)
    legal_line: str | None = Field(default=None, max_length=300)
    sponsors_title: str | None = Field(default=None, max_length=80)
    # A whole list at a time: the club reorders by dragging, and a patch that
    # could only append would make that impossible to express.
    sponsors: list[Sponsor] | None = Field(default=None, max_length=24)
    # On `club`, not `club_branding` — but this is the page where a club edits
    # how its name appears, and sending them to a different screen for the two
    # words in their own masthead is a boundary that serves nobody.
    display_name: str | None = Field(default=None, min_length=2, max_length=160)
    short_name: str | None = Field(default=None, min_length=1, max_length=8)
    founded_year: int | None = Field(default=None, ge=1800, le=2100)

    @field_validator("template")
    @classmethod
    def _known_template(cls, value: str | None) -> str | None:
        if value is not None and value not in SITE_TEMPLATES:
            raise ValueError(f"must be one of {', '.join(SITE_TEMPLATES)}")
        return value

    @field_validator("color_mode")
    @classmethod
    def _known_mode(cls, value: str | None) -> str | None:
        if value is not None and value not in COLOR_MODES:
            raise ValueError(f"must be one of {', '.join(COLOR_MODES)}")
        return value

    @field_validator("color_primary", "color_secondary", "color_accent")
    @classmethod
    def _valid_hex(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return normalise(value)
        except InvalidColor as exc:
            raise ValueError(str(exc)) from exc


def _check(color: str | None) -> ColorCheck | None:
    if not color:
        return None
    result = assess(color)
    advice = None
    if not result.meets_aa_as_text:
        advice = (
            f"Too light for body text on white ({result.contrast_on_white}:1, "
            f"AA needs {AA_NORMAL_TEXT}:1). Links and labels will use "
            f"{result.text_on_light} instead; the colour itself is still used for "
            "buttons and accents."
        )
    elif not result.meets_aa_as_surface:
        advice = (
            f"Text on a filled button in this colour is below {AA_NON_TEXT}:1. "
            "Consider a darker or lighter shade."
        )
    return ColorCheck(
        color=result.color,
        on_color=result.on_color,
        text_variant=result.text_on_light,
        was_adjusted=result.was_adjusted,
        contrast_on_white=result.contrast_on_white,
        meets_aa_as_text=result.meets_aa_as_text,
        meets_aa_as_surface=result.meets_aa_as_surface,
        advice=advice,
    )


def _to_response(
    branding: ClubBranding,
    media: dict[UUID, str] | None = None,
    club: Club | None = None,
) -> BrandingOut:
    checks = {
        name: check
        for name, check in (
            ("primary", _check(branding.color_primary)),
            ("secondary", _check(branding.color_secondary)),
            ("accent", _check(branding.color_accent)),
        )
        if check is not None
    }
    return BrandingOut(
        club_id=branding.club_id,
        template=branding.template,
        color_mode=branding.color_mode,
        color_primary=branding.color_primary,
        color_secondary=branding.color_secondary,
        color_accent=branding.color_accent,
        tagline=branding.tagline,
        social=branding.social or {},
        announcement_text=branding.announcement_text,
        announcement_is_active=branding.announcement_is_active,
        tickets_url=branding.tickets_url,
        tickets_label=branding.tickets_label,
        crest_media_id=branding.crest_media_id,
        hero_media_id=branding.hero_media_id,
        crest_url=(media or {}).get(branding.crest_media_id),
        hero_url=(media or {}).get(branding.hero_media_id),
        contact_email=branding.contact_email,
        contact_phone=branding.contact_phone,
        address=branding.address,
        legal_line=branding.legal_line,
        sponsors_title=branding.sponsors_title,
        sponsors=_sponsors_out(branding, media or {}),
        display_name=club.display_name if club else None,
        short_name=club.short_name if club else None,
        founded_year=club.founded_year if club else None,
        palette=build_palette(
            branding.color_primary, branding.color_secondary, branding.color_accent
        ),
        checks=checks,
    )


def _sponsors_out(branding: ClubBranding, media: dict[UUID, str]) -> list[dict]:
    """Sponsors with their logos resolved.

    A logo whose asset has been deleted resolves to nothing rather than to a
    broken image: the sponsor keeps its name and its link, which is the part
    that was agreed in writing.
    """
    out: list[dict] = []
    for sponsor in branding.sponsors or []:
        raw = sponsor.get("media_id")
        out.append(
            {
                "name": sponsor.get("name", ""),
                "url": sponsor.get("url"),
                "media_id": raw,
                "logo_url": media.get(UUID(raw)) if raw else None,
            }
        )
    return out


def _sponsor_asset_ids(branding: ClubBranding) -> list[UUID]:
    ids: list[UUID] = []
    for sponsor in branding.sponsors or []:
        raw = sponsor.get("media_id")
        if raw:
            try:
                ids.append(UUID(raw))
            except (ValueError, AttributeError, TypeError):
                # A malformed id in stored JSON is a data problem, not a reason
                # to fail the club's whole design screen.
                continue
    return ids


async def _media_urls(db: Db, branding: ClubBranding) -> dict[UUID, str]:
    """URLs for every image the design references.

    One query for all of them, and none at all when a club has chosen none —
    which is the normal case for one that has just signed up.
    """
    wanted = [
        asset_id
        for asset_id in (branding.crest_media_id, branding.hero_media_id)
        if asset_id is not None
    ] + _sponsor_asset_ids(branding)
    if not wanted:
        return {}
    assets = await db.scalars(select(MediaAsset).where(MediaAsset.id.in_(wanted)))
    return {asset.id: storage.public_url(asset.storage_key) for asset in assets}


async def _load(db: Db, ctx: RequestContext, club_id: UUID) -> ClubBranding:
    club = await db.scalar(select(Club).where(Club.id == club_id, Club.tenant_id == ctx.tenant))
    if club is None:
        raise NotFound(object_type="club", object_id=str(club_id))

    branding = await db.scalar(select(ClubBranding).where(ClubBranding.club_id == club_id))
    if branding is None:
        # Every club has branding; create the default row lazily so clubs that
        # predate this feature behave like new ones.
        branding = ClubBranding(tenant_id=ctx.tenant, club_id=club_id)
        db.add(branding)
        await db.flush()
    return branding


@router.get(
    "/clubs/{club_id}/branding",
    response_model=BrandingOut,
    summary="Get design settings",
)
async def get_branding(
    club_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires("clubs.club.read"))],
) -> BrandingOut:
    branding = await _load(db, ctx, club_id)
    club = await db.scalar(select(Club).where(Club.id == club_id, Club.tenant_id == ctx.tenant))
    return _to_response(branding, await _media_urls(db, branding), club)


@router.put(
    "/clubs/{club_id}/branding",
    response_model=BrandingOut,
    summary="Update design settings",
)
async def update_branding(
    club_id: UUID,
    payload: BrandingUpdate,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires("clubs.club.update"))],
) -> BrandingOut:
    branding = await _load(db, ctx, club_id)

    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise ValidationFailed("No changes were supplied.")

    if "sponsors" in changes:
        # JSONB holds JSON, and a UUID is not JSON. Dumped in json mode so the
        # asset id round-trips as the string the reader expects.
        changes["sponsors"] = [
            sponsor.model_dump(mode="json") for sponsor in payload.sponsors or []
        ]

    # Split by where the column lives, the same way the player editor does.
    club_changes: dict[str, object] = {
        field: changes.pop(field).strip()
        for field in ("display_name", "short_name")
        if field in changes and changes[field] is not None
    }
    if "founded_year" in changes:
        club_changes["founded_year"] = changes.pop("founded_year")

    before = {field: getattr(branding, field) for field in changes}
    for field, value in changes.items():
        setattr(branding, field, value)
    branding.updated_by = ctx.actor_id

    if club_changes:
        club = await db.scalar(
            select(Club).where(Club.id == club_id, Club.tenant_id == ctx.tenant)
        )
        if club is None:
            raise NotFound(object_type="club", object_id=str(club_id))
        before |= {field: getattr(club, field) for field in club_changes}
        for field, value in club_changes.items():
            setattr(club, field, value)
        changes |= club_changes

    AuditService(db).record(
        ctx,
        action="clubs.branding.update",
        object_type="club_branding",
        object_id=club_id,
        before=before,
        after=changes,
        club_id=club_id,
    )

    # The public site caches its config; without this a club changes its
    # colours and sees nothing for a minute, which reads as broken.
    publish(db, ClubBrandingChanged.of(club_id, tenant_id=ctx.tenant))

    await db.flush()
    club = await db.scalar(select(Club).where(Club.id == club_id, Club.tenant_id == ctx.tenant))
    return _to_response(branding, await _media_urls(db, branding), club)
