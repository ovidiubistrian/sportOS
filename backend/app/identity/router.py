"""Session bootstrap.

`GET /me` is the first call every authenticated frontend makes. It returns the
tenants the user may act in, the resolved permission keys and the club list —
everything the SPA needs to build navigation without guessing.

The permission list here is for *presentation*. Hiding a button is not
authorization; every route enforces independently.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Ctx, Db, bootstrap_session
from app.core.db import platform_session
from app.identity.service import IdentityService
from app.tenants.branding_models import ClubBranding
from app.tenants.colors import build_palette
from app.tenants.models import Club, Tenant

router = APIRouter(tags=["identity"])


class TenantSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    legal_name: str
    trading_name: str | None = None
    default_locale: str
    # The newsroom needs to know which languages an article can exist in.
    supported_locales: list[str] = []
    default_currency: str
    timezone: str
    status: str
    is_demo: bool


class ClubSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    display_name: str
    short_name: str
    template: str = "CLASSIC"
    color_primary: str = "#1F4B99"
    # Derived server-side so the admin shell and the public site are themed
    # from the same maths — a club never sees two different blues.
    palette: dict[str, str] = Field(default_factory=dict)
    # The club's identity in the shared competition directory, so the admin can
    # tell which row of a league table is its own.
    directory_club_id: UUID | None = None


class Workspace(BaseModel):
    """One club the user may enter, and the tenant it belongs to.

    The admin is one application at one address; the club slug in the URL is
    what says *which* club you are working in. This list is what makes that
    resolvable at sign-in, before any tenant has been chosen.

    It is a routing aid, never an authorization input: the slug picks an entry
    from this list, and the resulting tenant id is sent as `X-Tenant-Id`, which
    the API re-validates against the user's memberships on every request.
    """

    tenant_id: UUID
    tenant_name: str
    club: ClubSummary


class MeResponse(BaseModel):
    user_id: UUID
    email: str
    is_platform_user: bool
    active_tenant: TenantSummary | None
    tenants: list[TenantSummary]
    clubs: list[ClubSummary]
    # Every club across every tenant this user belongs to.
    workspaces: list[Workspace]
    permissions: list[str]


def _to_summary(club: Club, branding: ClubBranding | None) -> ClubSummary:
    primary = branding.color_primary if branding else "#1F4B99"
    return ClubSummary(
        id=club.id,
        slug=club.slug,
        display_name=club.display_name,
        short_name=club.short_name,
        template=branding.template if branding else "CLASSIC",
        color_primary=primary,
        palette=build_palette(
            primary,
            branding.color_secondary if branding else None,
            branding.color_accent if branding else None,
        ),
        directory_club_id=club.directory_club_id,
    )


async def _workspaces(memberships: Sequence[Tenant]) -> list[Workspace]:
    """Clubs across every tenant this user is a member of.

    Cross-tenant by necessity: the answer to "which workspaces may I enter?"
    cannot be produced from inside a single tenant's row-level scope, and it is
    needed *before* a tenant is chosen. Bounded to the caller's own membership
    list, which is itself derived from live role assignments — so this reads
    across tenants, but only across the user's own.
    """
    if not memberships:
        return []

    by_id = {tenant.id: tenant for tenant in memberships}
    async with platform_session(reason="resolve the workspaces a user may enter") as session:
        rows = await session.execute(
            select(Club, ClubBranding)
            .outerjoin(ClubBranding, ClubBranding.club_id == Club.id)
            .where(Club.tenant_id.in_(by_id), Club.status == "ACTIVE")
            .order_by(Club.display_name)
        )
        return [
            Workspace(
                tenant_id=club.tenant_id,
                tenant_name=by_id[club.tenant_id].trading_name
                or by_id[club.tenant_id].legal_name,
                club=_to_summary(club, branding),
            )
            for club, branding in rows
        ]


@router.get("/me", response_model=MeResponse, summary="Current session")
async def me(
    ctx: Ctx,
    db: Db,
    bootstrap: Annotated[AsyncSession, Depends(bootstrap_session)],
) -> MeResponse:
    memberships = await IdentityService(bootstrap).tenant_memberships(ctx.actor.user_id)

    clubs: list[ClubSummary] = []
    if ctx.tenant_id is not None:
        # RLS would scope this anyway; the explicit predicate is here so the
        # query is correct on its own terms and not only because of a policy.
        rows = await db.execute(
            select(Club, ClubBranding)
            .outerjoin(ClubBranding, ClubBranding.club_id == Club.id)
            .where(Club.tenant_id == ctx.tenant, Club.status == "ACTIVE")
            .order_by(Club.display_name)
        )
        clubs = [_to_summary(club, branding) for club, branding in rows]

    workspaces = await _workspaces(memberships)
    active = next((t for t in memberships if t.id == ctx.tenant_id), None)
    permissions = sorted(ctx.permissions.keys) if ctx.permissions else []

    return MeResponse(
        user_id=ctx.actor.user_id,
        email=ctx.actor.email,
        is_platform_user=ctx.actor.is_platform_user,
        active_tenant=TenantSummary.model_validate(active) if active else None,
        tenants=[TenantSummary.model_validate(t) for t in memberships],
        clubs=clubs,
        workspaces=workspaces,
        permissions=permissions,
    )
