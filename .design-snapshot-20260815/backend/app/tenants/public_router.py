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
from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, or_, select

from app.cms.models import ContentItem, ContentTranslation
from app.cms.schemas import PublicArticle, PublicArticleSummary
from app.cms.service import pick_translation
from app.competitions.models import (
    Competition,
    CompetitionEntry,
    CompetitionSeason,
    DirectoryClub,
    Match,
)
from app.competitions.standings import compute_table
from app.core.db import platform_session, tenant_session
from app.core.errors import NotFound
from app.identity.models import Person
from app.media import storage
from app.media.models import MediaAsset
from app.players.models import Player, PlayerRegistration
from app.teams.models import Team
from app.tenants.branding_models import ClubBranding
from app.tenants.colors import build_palette
from app.tenants.models import Club, Tenant
from app.tenants.site_service import SiteRoute, resolve_host

router = APIRouter(prefix="/public", tags=["public"])

# News and fixtures change often; club identity does not.
SITE_CACHE = "public, max-age=60, stale-while-revalidate=300"
CONTENT_CACHE = "public, max-age=120, stale-while-revalidate=600"


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
    announcement: str | None = None
    tickets_url: str | None = None
    tickets_label: str | None = None
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


def _asset_url(images: dict[UUID, MediaAsset], asset_id: UUID | None) -> str | None:
    asset = images.get(asset_id) if asset_id else None
    return storage.public_url(asset.storage_key) if asset else None


def _asset_alt(images: dict[UUID, MediaAsset], asset_id: UUID | None) -> str | None:
    asset = images.get(asset_id) if asset_id else None
    return asset.alt_text if asset else None


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
        ]
        if wanted:
            images = {
                asset.id: asset
                for asset in await session.scalars(
                    select(MediaAsset).where(MediaAsset.id.in_(wanted))
                )
            }

    template = branding.template if branding else "CLASSIC"
    primary = branding.color_primary if branding else "#1F4B99"
    secondary = branding.color_secondary if branding else None
    accent = branding.color_accent if branding else None

    return SiteOut(
        club_id=club.id,
        slug=club.slug,
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
            announcement=(
                branding.announcement_text
                if branding and branding.announcement_is_active
                else None
            ),
            tickets_url=branding.tickets_url if branding else None,
            tickets_label=branding.tickets_label if branding else None,
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
            .order_by(ContentItem.is_pinned.desc(), ContentItem.published_at.desc())
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
            cover_url=(
                _asset_url(
                    {
                        asset.id: asset
                        for asset in await session.scalars(
                            select(MediaAsset).where(MediaAsset.id == item.cover_media_id)
                        )
                    },
                    item.cover_media_id,
                )
                if item.cover_media_id
                else None
            ),
            served_locale_fallback=bool(locale and chosen.locale != locale),
        )


class PublicClubRef(BaseModel):
    name: str
    short_name: str
    crest_url: str | None


class PublicMatch(BaseModel):
    id: UUID
    competition: str
    round_label: str | None
    home: PublicClubRef
    away: PublicClubRef
    kickoff_at: datetime | None
    kickoff_is_confirmed: bool
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

        return [
            PublicMatch(
                id=m.id,
                competition=names.get(m.competition_season_id, ""),
                round_label=(
                    m.round_label or (f"Etapa {m.round_number}" if m.round_number else None)
                ),
                home=ref(m.home_club_id),
                away=ref(m.away_club_id),
                kickoff_at=m.kickoff_at,
                kickoff_is_confirmed=m.kickoff_is_confirmed,
                venue_name=m.venue_name,
                status=m.status,
                home_score=m.home_score,
                away_score=m.away_score,
                ticket_url=m.ticket_url,
                is_home=m.home_club_id == club.directory_club_id,
            )
            for m in matches
        ]


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

        season = await session.scalar(
            select(CompetitionSeason)
            .join(Competition, Competition.id == CompetitionSeason.competition_id)
            .join(
                CompetitionEntry,
                CompetitionEntry.competition_season_id == CompetitionSeason.id,
            )
            .where(
                CompetitionEntry.directory_club_id == club.directory_club_id,
                Competition.format == "LEAGUE",
                CompetitionSeason.is_current.is_(True),
            )
            .order_by(Competition.tier)
        )
        if season is None:
            return []

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
