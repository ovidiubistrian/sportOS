"""Public API — unauthenticated, cacheable, host-scoped.

Everything here is served to anonymous visitors of a club's website, so:

  * the tenant comes from the Host header, never from a parameter;
  * responses carry public cache headers and are safe behind a CDN;
  * only published, public-facing fields are exposed — no personal contact
    details, no internal status, no counts that reveal commercial information.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, func, or_, select

from app.cms.models import ContentItem, ContentTranslation
from app.cms.schemas import PublicArticle, PublicArticleSummary
from app.cms.service import pick_translation
from app.competitions.models import (
    ClubSeasonRecord,
    Competition,
    CompetitionEntry,
    CompetitionSeason,
    DirectoryClub,
    Match,
    MatchEvent,
    MatchLineup,
    MatchLineupPlayer,
)
from app.competitions.standings import compute_table
from app.core.db import platform_session, tenant_session
from app.core.errors import NotFound
from app.identity.models import Person
from app.media import storage
from app.media.models import MediaAsset
from app.payments.registry import can_take_card
from app.players.models import Player, PlayerRegistration
from app.sports.registry import profile
from app.teams.models import Team, TeamStaff
from app.tenants.branding_models import ClubBranding
from app.tenants.colors import build_palette
from app.tenants.models import Club, Tenant
from app.tenants.site_service import SiteRoute, resolve_host

router = APIRouter(prefix="/public", tags=["public"])

# News and fixtures change often; club identity does not.
SITE_CACHE = "public, max-age=60, stale-while-revalidate=300"
CONTENT_CACHE = "public, max-age=120, stale-while-revalidate=600"


class SponsorOut(BaseModel):
    name: str
    url: str | None = None
    logo_url: str | None = None


class BrandingOut(BaseModel):
    template: str
    color_mode: str
    color_primary: str
    color_secondary: str | None
    color_accent: str | None
    tagline: str | None
    social: dict
    # Resolved from the asset ids, so a deleted image degrades to no crest
    # rather than to a broken URL on the club's home page.
    crest_url: str | None = None
    crest_alt: str | None = None
    hero_url: str | None = None
    hero_alt: str | None = None
    # A CSS `object-position`, or null when the picture is centred.
    hero_focus: str | None = None
    # Whether this club can take a card at all. The shop asks before offering
    # one: a button that answers "not available here" is worse than no button.
    accepts_cards: bool = False
    # How this club wants a team sheet shown: a list of names, or the eleven
    # arranged on a pitch. Defaults to the list, which is what the provider's
    # data supports for every league — see `club_branding.lineup_display`.
    lineup_display: str = "LIST"
    announcement: str | None = None
    tickets_url: str | None = None
    tickets_label: str | None = None
    # The footer, as the club filled it in. Every field optional: a club that
    # has said nothing gets a footer with its name and nothing else, which is
    # what it had before any of this existed.
    contact_email: str | None = None
    contact_phone: str | None = None
    address: str | None = None
    legal_line: str | None = None
    sponsors_title: str | None = None
    sponsors: list[SponsorOut] = Field(default_factory=list)
    # Derived, never stored: improving the contrast maths fixes every club at
    # once instead of needing a backfill.
    palette: dict[str, str]


class SiteOut(BaseModel):
    club_id: UUID
    slug: str
    name: str
    short_name: str
    founded_year: int | None
    country_code: str
    locale: str
    # Every language this club publishes in, so a reader's browser can be
    # matched against what actually exists rather than against a platform list.
    locales: list[str]
    timezone: str
    # What the club plays, and the two facts a website needs about it: what one
    # unit of score is called, and whether a match can be drawn. Sent so the
    # site can say "puncte" to a basketball club without the templates knowing
    # anything about basketball.
    sport: str
    scoring_unit: str
    draws_possible: bool
    branding: BrandingOut


class PublicTeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    code: str
    age_group: str | None
    level: str
    is_academy: bool


class PublicPlayerOut(BaseModel):
    id: UUID
    name: str
    shirt_number: int | None
    position: str | None
    photo_url: str | None = None


class PublicStaffOut(BaseModel):
    """A member of a team's staff, as the club presents them.

    Only the ones the club has marked public. A volunteer physio has not
    necessarily agreed to appear on a website, and the default cannot be that
    they have.
    """

    id: UUID
    name: str
    role: str
    title: str | None
    photo_url: str | None = None


def _sponsor_ids(branding: object | None) -> list[UUID]:
    """Asset ids inside the sponsors JSON, for the one image query."""
    ids: list[UUID] = []
    for sponsor in getattr(branding, "sponsors", None) or []:
        raw = sponsor.get("media_id")
        if not raw:
            continue
        try:
            ids.append(UUID(raw))
        except (ValueError, AttributeError, TypeError):
            continue
    return ids


def _sponsors(branding: object | None, images: dict[UUID, MediaAsset]) -> list[SponsorOut]:
    """A sponsor keeps its name and link even when its logo has been deleted."""
    out: list[SponsorOut] = []
    for sponsor in getattr(branding, "sponsors", None) or []:
        name = (sponsor.get("name") or "").strip()
        if not name:
            continue
        raw = sponsor.get("media_id")
        asset_id: UUID | None = None
        if raw:
            try:
                asset_id = UUID(raw)
            except (ValueError, AttributeError, TypeError):
                asset_id = None
        out.append(
            SponsorOut(
                name=name,
                url=sponsor.get("url"),
                logo_url=_asset_url(images, asset_id),
            )
        )
    return out


def _asset_url(images: dict[UUID, MediaAsset], asset_id: UUID | None) -> str | None:
    asset = images.get(asset_id) if asset_id else None
    return storage.public_url(asset.storage_key) if asset else None


def _asset_alt(images: dict[UUID, MediaAsset], asset_id: UUID | None) -> str | None:
    asset = images.get(asset_id) if asset_id else None
    return asset.alt_text if asset else None


def _asset_focus(images: dict[UUID, MediaAsset], asset_id: UUID | None) -> str | None:
    """The focal point as a CSS `object-position`, ready to use.

    Sent as the finished string rather than two numbers because every consumer
    would otherwise write the same multiplication, and a hero that is nearly
    3:1 on a desktop and nearly square on a phone is exactly where an
    off-by-one in that sum would be hardest to spot.

    `None` at dead centre, which is the CSS default: no reason to put a
    declaration on every image to say "unchanged".
    """
    asset = images.get(asset_id) if asset_id else None
    if asset is None or (asset.focal_x == 0.5 and asset.focal_y == 0.5):
        return None
    return f"{asset.focal_x * 100:g}% {asset.focal_y * 100:g}%"


async def _route_or_404(host: str | None) -> SiteRoute:
    route = await resolve_host(host)
    if route is None:
        raise NotFound("No club is published on this domain.")
    return route


def _host(forwarded: str | None, header_host: str | None) -> str | None:
    """The proxy's X-Forwarded-Host, falling back to Host.

    There is deliberately no query-parameter override. A club is identified by
    the domain the visitor actually arrived on and nothing else — an override
    would be a parameter that selects a tenant, which is the one thing the
    whole tenancy design forbids.
    """
    return forwarded or header_host


@router.get(
    "/domains/check",
    summary="Certificate issuance guard for the reverse proxy",
    include_in_schema=False,
)
async def check_domain(domain: Annotated[str, Query(max_length=253)]) -> Response:
    """Caddy calls this before issuing a certificate for an unknown hostname.

    Without it, anyone could point DNS at us and drive certificate requests
    until we hit the CA's per-account rate limit — degrading every club, not
    just the attacker. A bare 200/404 is the whole contract; no body, and
    nothing that reveals which domains exist beyond the one asked about.
    """
    route = await resolve_host(domain)
    return Response(status_code=200 if route else 404)


@router.get("/site", response_model=SiteOut, summary="Club identity and theme")
async def get_site(
    response: Response,
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    host: Annotated[str | None, Header(alias="Host")] = None,
) -> SiteOut:
    route = await _route_or_404(_host(x_forwarded_host, host))
    response.headers["Cache-Control"] = SITE_CACHE

    async with tenant_session(route.tenant_id) as session:
        club = await session.scalar(select(Club).where(Club.id == route.club_id))
        if club is None or club.status != "ACTIVE":
            raise NotFound("No club is published on this domain.")
        branding = await session.scalar(
            select(ClubBranding).where(ClubBranding.club_id == route.club_id)
        )
        tenant_locales = await session.scalar(
            select(Tenant.supported_locales).where(Tenant.id == route.tenant_id)
        )

        # One query for both images, and none at all when neither is set —
        # which is the normal case for a club that has just signed up.
        images: dict[UUID, MediaAsset] = {}
        wanted = [
            asset_id
            for asset_id in (
                branding.crest_media_id if branding else None,
                branding.hero_media_id if branding else None,
            )
            if asset_id is not None
        ] + _sponsor_ids(branding)
        if wanted:
            images = {
                asset.id: asset
                for asset in await session.scalars(
                    select(MediaAsset).where(MediaAsset.id.in_(wanted))
                )
            }

        # Asked here, inside the tenant-bound transaction: the row this reads
        # is behind row-level security, and the setting that unlocks it dies
        # with the transaction.
        accepts_cards = await can_take_card(session, route.tenant_id)

    template = branding.template if branding else "CLASSIC"
    primary = branding.color_primary if branding else "#1F4B99"
    secondary = branding.color_secondary if branding else None
    accent = branding.color_accent if branding else None

    sport = profile(club.sport)
    return SiteOut(
        club_id=club.id,
        slug=club.slug,
        sport=sport.key,
        scoring_unit=sport.scoring_unit,
        draws_possible=sport.draws_possible,
        name=club.display_name,
        short_name=club.short_name,
        founded_year=club.founded_year,
        country_code=club.country_code,
        locale=club.default_locale,
        locales=list(tenant_locales or [club.default_locale]),
        timezone=club.timezone,
        branding=BrandingOut(
            template=template,
            color_mode=branding.color_mode if branding else "LIGHT",
            color_primary=primary,
            color_secondary=secondary,
            color_accent=accent,
            tagline=branding.tagline if branding else None,
            social=branding.social if branding else {},
            crest_url=_asset_url(images, branding.crest_media_id if branding else None),
            crest_alt=_asset_alt(images, branding.crest_media_id if branding else None),
            hero_url=_asset_url(images, branding.hero_media_id if branding else None),
            hero_alt=_asset_alt(images, branding.hero_media_id if branding else None),
            hero_focus=_asset_focus(images, branding.hero_media_id if branding else None),
            accepts_cards=accepts_cards,
            lineup_display=branding.lineup_display if branding else "LIST",
            announcement=(
                branding.announcement_text
                if branding and branding.announcement_is_active
                else None
            ),
            tickets_url=branding.tickets_url if branding else None,
            tickets_label=branding.tickets_label if branding else None,
            contact_email=branding.contact_email if branding else None,
            contact_phone=branding.contact_phone if branding else None,
            address=branding.address if branding else None,
            legal_line=branding.legal_line if branding else None,
            sponsors_title=branding.sponsors_title if branding else None,
            sponsors=_sponsors(branding, images),
            palette=build_palette(primary, secondary, accent),
        ),
    )


@router.get("/teams", response_model=list[PublicTeamOut], summary="Public team list")
async def list_teams(
    response: Response,
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    host: Annotated[str | None, Header(alias="Host")] = None,
) -> list[PublicTeamOut]:
    route = await _route_or_404(_host(x_forwarded_host, host))
    response.headers["Cache-Control"] = CONTENT_CACHE

    async with tenant_session(route.tenant_id) as session:
        rows = await session.scalars(
            select(Team)
            .where(
                Team.tenant_id == route.tenant_id,
                Team.club_id == route.club_id,
                Team.status == "ACTIVE",
            )
            .order_by(Team.is_academy, Team.name)
        )
        return [PublicTeamOut.model_validate(row) for row in rows]


@router.get(
    "/teams/{team_id}/staff",
    response_model=list[PublicStaffOut],
    summary="Public team staff",
)
async def team_staff(
    team_id: UUID,
    response: Response,
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    host: Annotated[str | None, Header(alias="Host")] = None,
) -> list[PublicStaffOut]:
    """The touchline, in the order a club would introduce it."""
    route = await _route_or_404(_host(x_forwarded_host, host))
    response.headers["Cache-Control"] = CONTENT_CACHE

    async with tenant_session(route.tenant_id) as session:
        rows = list(
            await session.execute(
                select(
                    TeamStaff.id,
                    Person.display_name,
                    TeamStaff.role,
                    TeamStaff.title,
                    TeamStaff.photo_media_id,
                )
                .join(
                    Person,
                    and_(
                        Person.id == TeamStaff.person_id,
                        Person.tenant_id == TeamStaff.tenant_id,
                    ),
                )
                .where(
                    TeamStaff.tenant_id == route.tenant_id,
                    TeamStaff.club_id == route.club_id,
                    TeamStaff.team_id == team_id,
                    TeamStaff.is_public.is_(True),
                )
                .order_by(TeamStaff.sort_order, Person.display_name)
            )
        )
        photo_ids = {row[4] for row in rows if row[4]}
        photos = (
            {
                asset.id: asset
                for asset in await session.scalars(
                    select(MediaAsset).where(MediaAsset.id.in_(photo_ids))
                )
            }
            if photo_ids
            else {}
        )
        return [
            PublicStaffOut(
                id=staff_id,
                name=name,
                role=role,
                title=title,
                photo_url=_asset_url(photos, photo_id),
            )
            for staff_id, name, role, title, photo_id in rows
        ]


@router.get(
    "/teams/{team_id}/squad",
    response_model=list[PublicPlayerOut],
    summary="Public squad list",
)
async def team_squad(
    team_id: UUID,
    response: Response,
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    host: Annotated[str | None, Header(alias="Host")] = None,
) -> list[PublicPlayerOut]:
    route = await _route_or_404(_host(x_forwarded_host, host))
    response.headers["Cache-Control"] = CONTENT_CACHE

    async with tenant_session(route.tenant_id) as session:
        team = await session.scalar(
            select(Team).where(Team.id == team_id, Team.club_id == route.club_id)
        )
        if team is None:
            raise NotFound("Unknown team.")

        # Name, number and position only. Date of birth is withheld: publishing
        # a minor's birth date alongside their name and club is a safeguarding
        # problem, not a feature.
        rows = await session.execute(
            select(
                Player.id,
                Person.display_name,
                PlayerRegistration.shirt_number,
                Player.primary_position,
                Player.photo_media_id,
            )
            .join(
                Player,
                and_(
                    Player.person_id == Person.id,
                    Player.tenant_id == Person.tenant_id,
                ),
            )
            .join(
                PlayerRegistration,
                and_(
                    PlayerRegistration.player_id == Player.id,
                    PlayerRegistration.tenant_id == Player.tenant_id,
                    PlayerRegistration.ended_on.is_(None),
                ),
            )
            .where(
                Player.tenant_id == route.tenant_id,
                PlayerRegistration.team_id == team_id,
                Player.status == "REGISTERED",
            )
            .order_by(PlayerRegistration.shirt_number.nulls_last(), Person.display_name)
        )

        squad = list(rows)
        photo_ids = {row[4] for row in squad if row[4]}
        photos = (
            {
                asset.id: asset
                for asset in await session.scalars(
                    select(MediaAsset).where(MediaAsset.id.in_(photo_ids))
                )
            }
            if photo_ids
            else {}
        )

        return [
            PublicPlayerOut(
                id=player_id,
                name=name,
                shirt_number=number,
                position=position,
                photo_url=_asset_url(photos, photo_id),
            )
            for player_id, name, number, position, photo_id in squad
        ]


@router.get(
    "/tls-check",
    include_in_schema=False,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="May a certificate be issued for this hostname?",
)
async def tls_check(
    domain: Annotated[str, Query(max_length=253)],
    response: Response,
) -> None:
    """The gate in front of automatic certificate issuance.

    Every club has its own hostname, and clubs are created while the server is
    running — so certificates cannot be baked into configuration. The proxy is
    configured to obtain one on demand, and asks this endpoint first.

    Without that gate anybody could point a DNS record at the server and make
    it request certificates on their behalf, which is both a way to exhaust the
    certificate authority's rate limit and a way to have a stranger's domain
    served by us. The answer is simply "is this a hostname we know", which is
    the same question the public site already resolves on every request.
    """
    response.headers["Cache-Control"] = "no-store"
    if await resolve_host(domain.strip().lower()) is None:
        raise NotFound("Unknown domain.")


@router.get("/health", include_in_schema=False, status_code=status.HTTP_200_OK)
async def public_health() -> dict[str, str]:
    return {"status": "ok"}


# --- news -------------------------------------------------------------------
# Published content only. `status = 'PUBLISHED'` is applied in the query rather
# than filtered afterwards, so a draft cannot leak through a pagination bug.


async def _published_items(session, route: SiteRoute, limit: int, offset: int):
    return list(
        await session.scalars(
            select(ContentItem)
            .where(
                ContentItem.tenant_id == route.tenant_id,
                ContentItem.club_id == route.club_id,
                ContentItem.kind == "ARTICLE",
                ContentItem.status == "PUBLISHED",
            )
            # Newest first, and `created_at` breaks the tie. Several articles
            # published in the same minute — a club catching up on a season's
            # news in one sitting — otherwise came back in whatever order the
            # database found them, which changed between requests and made the
            # front page look like it was shuffling itself.
            .order_by(
                ContentItem.is_pinned.desc(),
                ContentItem.published_at.desc(),
                ContentItem.created_at.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
    )


@router.get(
    "/news",
    response_model=list[PublicArticleSummary],
    summary="Published articles",
)
async def list_news(
    response: Response,
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    host: Annotated[str | None, Header(alias="Host")] = None,
    locale: Annotated[str | None, Query(max_length=10)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 12,
    offset: Annotated[int, Query(ge=0, le=500)] = 0,
) -> list[PublicArticleSummary]:
    route = await _route_or_404(_host(x_forwarded_host, host))
    response.headers["Cache-Control"] = CONTENT_CACHE

    async with tenant_session(route.tenant_id) as session:
        club = await session.scalar(select(Club).where(Club.id == route.club_id))
        default_locale = club.default_locale if club else "en"

        items = await _published_items(session, route, limit, offset)
        if not items:
            return []

        by_item: dict[UUID, list[ContentTranslation]] = {item.id: [] for item in items}
        for translation in await session.scalars(
            select(ContentTranslation).where(ContentTranslation.content_item_id.in_(by_item))
        ):
            by_item[translation.content_item_id].append(translation)

        cover_ids = {item.cover_media_id for item in items if item.cover_media_id}
        covers = (
            {
                asset.id: asset
                for asset in await session.scalars(
                    select(MediaAsset).where(MediaAsset.id.in_(cover_ids))
                )
            }
            if cover_ids
            else {}
        )

        summaries = []
        for item in items:
            chosen = pick_translation(by_item[item.id], locale, default_locale)
            if chosen is None:
                # Published with no translation at all should be impossible, but
                # skipping beats rendering a blank card.
                continue
            summaries.append(
                PublicArticleSummary(
                    id=item.id,
                    slug=chosen.slug,
                    locale=chosen.locale,
                    title=chosen.title,
                    excerpt=chosen.excerpt,
                    published_at=item.published_at,
                    is_pinned=item.is_pinned,
                    cover_url=_asset_url(covers, item.cover_media_id),
                    cover_focus=_asset_focus(covers, item.cover_media_id),
                    article_type=item.article_type,
                )
            )
        return summaries


@router.get(
    "/news/{slug}",
    response_model=PublicArticle,
    summary="One published article",
)
async def get_article(
    slug: str,
    response: Response,
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    host: Annotated[str | None, Header(alias="Host")] = None,
    locale: Annotated[str | None, Query(max_length=10)] = None,
) -> PublicArticle:
    route = await _route_or_404(_host(x_forwarded_host, host))
    response.headers["Cache-Control"] = CONTENT_CACHE

    async with tenant_session(route.tenant_id) as session:
        club = await session.scalar(select(Club).where(Club.id == route.club_id))
        default_locale = club.default_locale if club else "en"

        # Slugs are unique per club per locale, so the same article can be
        # reached by its Romanian or its English slug.
        match = await session.scalar(
            select(ContentTranslation).where(
                ContentTranslation.club_id == route.club_id,
                ContentTranslation.slug == slug,
            )
        )
        if match is None:
            raise NotFound("No such article.")

        item = await session.scalar(
            select(ContentItem).where(
                ContentItem.id == match.content_item_id,
                ContentItem.status == "PUBLISHED",
            )
        )
        if item is None:
            # Draft, scheduled or archived: indistinguishable from absent.
            raise NotFound("No such article.")

        translations = list(
            await session.scalars(
                select(ContentTranslation).where(ContentTranslation.content_item_id == item.id)
            )
        )
        chosen = pick_translation(translations, locale or match.locale, default_locale)
        if chosen is None:
            raise NotFound("No such article.")

        # The whole asset, not just its URL: the focal point comes off it too.
        cover: dict[UUID, MediaAsset] = (
            {
                asset.id: asset
                for asset in await session.scalars(
                    select(MediaAsset).where(MediaAsset.id == item.cover_media_id)
                )
            }
            if item.cover_media_id
            else {}
        )

        return PublicArticle(
            id=item.id,
            slug=chosen.slug,
            locale=chosen.locale,
            title=chosen.title,
            excerpt=chosen.excerpt,
            body=chosen.body or [],
            seo_title=chosen.seo_title,
            seo_description=chosen.seo_description,
            published_at=item.published_at,
            is_pinned=item.is_pinned,
            article_type=item.article_type,
            cover_url=_asset_url(cover, item.cover_media_id),
            cover_focus=_asset_focus(cover, item.cover_media_id),
            served_locale_fallback=bool(locale and chosen.locale != locale),
        )


class PublicClubRef(BaseModel):
    name: str
    short_name: str
    crest_url: str | None


class PublicMatchEvent(BaseModel):
    minute: int | None
    extra_minute: int | None
    kind: str
    detail: str | None
    player_name: str | None
    related_name: str | None
    # Which side it was for, so the timeline can put it on the right of the
    # page or the left without the reader having to match names.
    is_home: bool


class PublicLineupPlayer(BaseModel):
    name: str
    shirt_number: int | None = None
    position: str | None = None
    # "row:column" from the goalkeeper out, when somebody has placed them.
    # Null for a substitute, and for a starter nobody has arranged.
    grid: str | None = None


class PublicLineup(BaseModel):
    """One side's team sheet.

    `formation` and every `grid` are null for a league the provider does not
    cover fully — which is most of them below the top division. The site falls
    back to a list in that case rather than inventing a shape; see
    `club_branding.lineup_display`.
    """

    formation: str | None = None
    coach_name: str | None = None
    starters: list[PublicLineupPlayer] = Field(default_factory=list)
    substitutes: list[PublicLineupPlayer] = Field(default_factory=list)


class PublicMatch(BaseModel):
    id: UUID
    competition: str
    # A named round ("Finală") and a numbered one are different things, and the
    # number has to be labelled in the reader's language rather than the
    # server's — this used to build "Etapa 3" here, which an English club saw.
    round_label: str | None
    round_number: int | None = None
    home: PublicClubRef
    away: PublicClubRef
    kickoff_at: datetime | None
    kickoff_is_confirmed: bool
    # Minute of play while a match is on. Null otherwise — a stale minute on a
    # finished game reads as a live one.
    minute: int | None = None
    events: list[PublicMatchEvent] = Field(default_factory=list)
    # Absent until the provider publishes them, about an hour before kick-off.
    home_lineup: PublicLineup | None = None
    away_lineup: PublicLineup | None = None
    venue_name: str | None
    status: str
    home_score: int | None
    away_score: int | None
    ticket_url: str | None
    is_home: bool


class PublicTableRow(BaseModel):
    position: int
    club: PublicClubRef
    played: int
    won: int
    drawn: int
    lost: int
    goal_difference: int
    points: int
    form: list[str]
    is_us: bool


@router.get("/matches", response_model=list[PublicMatch], summary="Fixtures and results")
async def public_matches(
    response: Response,
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    host: Annotated[str | None, Header(alias="Host")] = None,
    upcoming: bool = True,
    limit: int = 5,
) -> list[PublicMatch]:
    """The next few fixtures, or the last few results.

    Cached briefly rather than long: a kick-off time can move on the morning of
    a match, and a supporter checking the site is the person it matters to.
    """
    route = await _route_or_404(_host(x_forwarded_host, host))
    response.headers["Cache-Control"] = CONTENT_CACHE

    async with platform_session(reason="public fixture list", routine=True) as session:
        club = await session.get(Club, route.club_id)
        if club is None or club.directory_club_id is None:
            return []

        stmt = select(Match).where(
            or_(
                Match.home_club_id == club.directory_club_id,
                Match.away_club_id == club.directory_club_id,
            )
        )
        if upcoming:
            stmt = stmt.where(Match.status.in_(("SCHEDULED", "LIVE"))).order_by(
                Match.kickoff_at
            )
        else:
            stmt = stmt.where(Match.status.in_(("FINISHED", "AWARDED"))).order_by(
                Match.kickoff_at.desc()
            )

        matches = list(await session.scalars(stmt.limit(min(limit, 20))))
        if not matches:
            return []

        club_ids = {m.home_club_id for m in matches} | {m.away_club_id for m in matches}
        directory = {
            row.id: row
            for row in await session.scalars(
                select(DirectoryClub).where(DirectoryClub.id.in_(club_ids))
            )
        }
        names = {
            row[0]: row[1]
            for row in (
                await session.execute(
                    select(CompetitionSeason.id, Competition.name)
                    .join(Competition, Competition.id == CompetitionSeason.competition_id)
                    .where(CompetitionSeason.id.in_({m.competition_season_id for m in matches}))
                )
            ).all()
        }

        def ref(club_id: UUID) -> PublicClubRef:
            entry = directory[club_id]
            return PublicClubRef(
                name=entry.name, short_name=entry.short_name, crest_url=entry.crest_url
            )

        # Team sheets, in two queries for the whole page rather than two per
        # match. Most fixtures have none — they are published about an hour
        # before kick-off — so this is usually a pair of empty results.
        sheets: dict[tuple[UUID, str], PublicLineup] = {}
        lineup_rows = list(
            await session.scalars(
                select(MatchLineup).where(MatchLineup.match_id.in_([m.id for m in matches]))
            )
        )
        if lineup_rows:
            squads: dict[UUID, list[MatchLineupPlayer]] = {}
            for player in await session.scalars(
                select(MatchLineupPlayer)
                .where(MatchLineupPlayer.lineup_id.in_([row.id for row in lineup_rows]))
                .order_by(MatchLineupPlayer.display_order)
            ):
                squads.setdefault(player.lineup_id, []).append(player)

            for row in lineup_rows:
                members = squads.get(row.id, [])
                sheets[(row.match_id, row.side)] = PublicLineup(
                    formation=row.formation,
                    coach_name=row.coach_name,
                    starters=[
                        PublicLineupPlayer(
                            name=p.name,
                            shirt_number=p.shirt_number,
                            position=p.position,
                            grid=p.grid,
                        )
                        for p in members
                        if p.is_starter
                    ],
                    substitutes=[
                        PublicLineupPlayer(
                            name=p.name,
                            shirt_number=p.shirt_number,
                            position=p.position,
                            grid=p.grid,
                        )
                        for p in members
                        if not p.is_starter
                    ],
                )

        # One query for every match's events rather than one per match.
        timeline: dict[UUID, list[MatchEvent]] = {}
        for event in await session.scalars(
            select(MatchEvent)
            .where(MatchEvent.match_id.in_([m.id for m in matches]))
            .order_by(MatchEvent.minute, MatchEvent.created_at)
        ):
            timeline.setdefault(event.match_id, []).append(event)

        return [
            PublicMatch(
                id=m.id,
                competition=names.get(m.competition_season_id, ""),
                round_label=m.round_label,
                round_number=m.round_number,
                home=ref(m.home_club_id),
                away=ref(m.away_club_id),
                kickoff_at=m.kickoff_at,
                kickoff_is_confirmed=m.kickoff_is_confirmed,
                minute=m.minute,
                venue_name=m.venue_name,
                status=m.status,
                home_score=m.home_score,
                away_score=m.away_score,
                ticket_url=m.ticket_url,
                is_home=m.home_club_id == club.directory_club_id,
                home_lineup=sheets.get((m.id, "HOME")),
                away_lineup=sheets.get((m.id, "AWAY")),
                events=[
                    PublicMatchEvent(
                        minute=e.minute,
                        extra_minute=e.extra_minute,
                        kind=e.kind,
                        detail=e.detail,
                        player_name=e.player_name,
                        related_name=e.related_name,
                        is_home=e.club_id == m.home_club_id,
                    )
                    for e in timeline.get(m.id, [])
                ],
            )
            for m in matches
        ]


class PublicSeasonRecord(BaseModel):
    season: str
    competition: str
    position: int | None
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    points: int
    outcome: str | None


class PublicClubHistory(BaseModel):
    founded_year: int | None
    venue_name: str | None
    venue_capacity: int | None
    city: str | None
    seasons: list[PublicSeasonRecord]
    # Derived, not stored: the provider has no honours endpoint, so a title is
    # a first place in a table rather than something somebody typed in.
    honours: list[str]


@router.get("/history", response_model=PublicClubHistory, summary="The club's record")
async def public_history(
    response: Response,
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    host: Annotated[str | None, Header(alias="Host")] = None,
) -> PublicClubHistory:
    """Season by season, newest first, plus the club's own facts."""
    route = await _route_or_404(_host(x_forwarded_host, host))
    response.headers["Cache-Control"] = CONTENT_CACHE

    empty = PublicClubHistory(
        founded_year=None,
        venue_name=None,
        venue_capacity=None,
        city=None,
        seasons=[],
        honours=[],
    )

    async with platform_session(reason="public club history", routine=True) as session:
        club = await session.get(Club, route.club_id)
        if club is None or club.directory_club_id is None:
            return empty

        entry = await session.get(DirectoryClub, club.directory_club_id)
        if entry is None:
            return empty

        rows = (
            await session.execute(
                select(ClubSeasonRecord, CompetitionSeason, Competition)
                .join(
                    CompetitionSeason,
                    CompetitionSeason.id == ClubSeasonRecord.competition_season_id,
                )
                .join(Competition, Competition.id == CompetitionSeason.competition_id)
                .where(ClubSeasonRecord.directory_club_id == entry.id)
                .order_by(CompetitionSeason.name.desc())
            )
        ).all()

        seasons = [
            PublicSeasonRecord(
                season=season.name,
                competition=competition.name,
                position=record.position,
                played=record.played,
                won=record.won,
                drawn=record.drawn,
                lost=record.lost,
                goals_for=record.goals_for,
                goals_against=record.goals_against,
                points=record.points,
                outcome=record.outcome,
            )
            for record, season, competition in rows
        ]

        honours = [
            f"{row.competition} {row.season}"
            for row in seasons
            if row.position == 1 and row.played > 0
        ]

        return PublicClubHistory(
            # The club's own answer wins over the feed's. A provider records
            # when the current legal entity was registered; a club knows when
            # it was founded, and those are rarely the same century for a side
            # that has been reorganised. The feed fills the gap, never
            # overwrites the answer.
            founded_year=club.founded_year or entry.founded_year,
            venue_name=entry.venue_name,
            venue_capacity=entry.venue_capacity,
            city=entry.city,
            seasons=seasons,
            honours=honours,
        )


async def _have_whole_division(session, season: CompetitionSeason) -> bool:
    """Do we hold fixtures for every club in this season, or only one club's?

    The distinction decides whether our own table can be trusted. With the
    division's full fixture list a computed table is accurate and always
    current; with one club's fixtures it would show that club on nine points
    and everybody else on nil.
    """
    entrants = await session.scalar(
        select(func.count(CompetitionEntry.id)).where(
            CompetitionEntry.competition_season_id == season.id
        )
    )
    if not entrants:
        return False

    sides = await session.execute(
        select(Match.home_club_id, Match.away_club_id).where(
            Match.competition_season_id == season.id
        )
    )
    seen: set[UUID] = set()
    for home, away in sides.all():
        seen.add(home)
        seen.add(away)
    return len(seen) >= entrants


@router.get("/table", response_model=list[PublicTableRow], summary="League table")
async def public_table(
    response: Response,
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    host: Annotated[str | None, Header(alias="Host")] = None,
) -> list[PublicTableRow]:
    """The table of the club's current league.

    Only a league has one — a cup has a bracket, and pretending otherwise would
    put a meaningless table on a cup page.
    """
    route = await _route_or_404(_host(x_forwarded_host, host))
    response.headers["Cache-Control"] = CONTENT_CACHE

    async with platform_session(reason="public league table", routine=True) as session:
        club = await session.get(Club, route.club_id)
        if club is None or club.directory_club_id is None:
            return []

        # The league they play most of their football in. Ordering by tier
        # only works for curated competitions; one created from a provider
        # feed has no tier, and the club's own fixture count says which
        # division is theirs without needing one.
        season = await session.scalar(
            select(CompetitionSeason)
            .join(Competition, Competition.id == CompetitionSeason.competition_id)
            .join(
                CompetitionEntry,
                CompetitionEntry.competition_season_id == CompetitionSeason.id,
            )
            .join(Match, Match.competition_season_id == CompetitionSeason.id)
            .where(
                CompetitionEntry.directory_club_id == club.directory_club_id,
                Competition.format == "LEAGUE",
                CompetitionSeason.is_current.is_(True),
                or_(
                    Match.home_club_id == club.directory_club_id,
                    Match.away_club_id == club.directory_club_id,
                ),
            )
            .group_by(CompetitionSeason.id)
            .order_by(func.count(Match.id).desc())
            .limit(1)
        )
        if season is None:
            return []

        # A season on the league feed has the competition's own table, every
        # club's row included. Computing one instead would show this club on
        # nine points and the other twenty-one on nil, because only this
        # club's fixtures are synced.
        published = (
            await session.execute(
                select(ClubSeasonRecord, DirectoryClub)
                .join(
                    DirectoryClub,
                    DirectoryClub.id == ClubSeasonRecord.directory_club_id,
                )
                .where(ClubSeasonRecord.competition_season_id == season.id)
                .order_by(ClubSeasonRecord.position)
            )
        ).all()
        # Our own fixtures win *when we have all of them*. A computed table
        # takes in this afternoon's results immediately, where the published
        # one is recalculated on the competition's own schedule — and its
        # `update` field is stamped at midnight whether or not it has, so it
        # cannot be used to tell the two apart.
        if published and not await _have_whole_division(session, season):
            return [
                PublicTableRow(
                    position=record.position or index + 1,
                    club=PublicClubRef(
                        name=entry.name,
                        short_name=entry.short_name,
                        crest_url=entry.crest_url,
                    ),
                    played=record.played,
                    won=record.won,
                    drawn=record.drawn,
                    lost=record.lost,
                    goal_difference=record.goals_for - record.goals_against,
                    points=record.points,
                    form=list(reversed((record.form or "")[-5:])),
                    is_us=entry.id == club.directory_club_id,
                )
                for index, (record, entry) in enumerate(published)
            ]

        rows = await compute_table(session, season.id)
        return [
            PublicTableRow(
                position=index + 1,
                club=PublicClubRef(
                    name=row.club_name,
                    short_name=row.club_short_name,
                    crest_url=row.crest_url,
                ),
                played=row.played,
                won=row.won,
                drawn=row.drawn,
                lost=row.lost,
                goal_difference=row.goal_difference,
                points=row.points,
                form=row.form,
                is_us=row.club_id == club.directory_club_id,
            )
            for index, row in enumerate(rows)
        ]
