"""The super-admin console.

Everything here runs on `platform_session`, which bypasses row-level security
and therefore states a reason on every entry — the audit trail for the one role
that can see across tenants is the only thing standing between "support" and
"read anybody's data".

Impersonation is the delicate part and is deliberately not a special case in
the request path. `get_context` already refuses any `X-Tenant-Id` the caller
does not hold a live role in, so impersonating is *granting a real role*, time
limited, attributed and revocable — which means it shows up in the same tables,
the same permission resolution and the same audit as every other grant.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select

from app.api.deps import Requires
from app.audit.service import AuditService
from app.authz.models import Role, RoleAssignment
from app.authz.scope import ScopeLevel
from app.billing.models import Plan, PlanFeature, PlanVersion, TenantSubscription
from app.billing.service import invalidate_entitlements
from app.competitions.models import Competition, Country
from app.core.context import RequestContext
from app.core.db import platform_session
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.ids import new_id
from app.core.locales import LOCALE_CODES, normalise
from app.players.models import Player
from app.tenants.models import Club, Tenant

router = APIRouter(prefix="/platform", tags=["platform"])

READ = Requires("platform.tenant.read", scope_level=ScopeLevel.PLATFORM)
MANAGE = Requires("platform.tenant.manage", scope_level=ScopeLevel.PLATFORM)
IMPERSONATE = Requires("platform.impersonate", scope_level=ScopeLevel.PLATFORM)
CURATE = Requires("platform.competition.manage", scope_level=ScopeLevel.PLATFORM)

TENANT_STATUSES = ("PENDING", "ACTIVE", "SUSPENDED", "CLOSED")

# Long enough to reproduce a problem, short enough that a forgotten session
# closes itself. Support work that needs longer needs a second grant, which is
# a second audit entry — the point.
IMPERSONATION_MAX = timedelta(hours=4)
IMPERSONATION_DEFAULT = timedelta(hours=1)


class TenantRow(BaseModel):
    id: UUID
    slug: str
    name: str
    status: str
    country_code: str
    default_locale: str
    supported_locales: list[str]
    default_currency: str
    plan: str | None
    subscription_status: str | None
    trial_ends_at: datetime | None
    clubs: int
    players: int
    created_at: datetime


class TenantUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str | None = None
    suspended_reason: str | None = Field(default=None, max_length=500)
    default_locale: str | None = None
    supported_locales: list[str] | None = None

    @field_validator("status")
    @classmethod
    def _known_status(cls, value: str | None) -> str | None:
        if value is not None and value not in TENANT_STATUSES:
            raise ValueError(f"must be one of {', '.join(TENANT_STATUSES)}")
        return value


class PlanFeatureOut(BaseModel):
    feature_key: str
    enabled: bool
    limit_value: int | None


class PlanOut(BaseModel):
    id: UUID
    key: str
    name: str
    tier: str
    version: int
    features: list[PlanFeatureOut]


class SubscriptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_key: str
    status: str = "ACTIVE"

    @field_validator("status")
    @classmethod
    def _known(cls, value: str) -> str:
        if value not in ("TRIALING", "ACTIVE", "PAST_DUE", "PAUSED", "CANCELLED"):
            raise ValueError("unknown subscription status")
        return value


class ImpersonationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Required, and stored. "Why were you in this club's data on Tuesday?" has
    # to have an answer that was written before the fact, not after it.
    reason: str = Field(min_length=8, max_length=500)
    minutes: int = Field(default=60, ge=5, le=240)


class ImpersonationOut(BaseModel):
    tenant_id: UUID
    tenant_name: str
    expires_at: datetime
    role: str


class CompetitionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    key: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=120)
    short_name: str | None = Field(default=None, max_length=16)
    format: str
    scope: str
    tier: int | None = Field(default=None, ge=1, le=12)
    sort_order: int = 0
    is_active: bool = True


class CompetitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    country_code: str | None = None
    key: str
    name: str
    short_name: str | None
    format: str
    scope: str
    tier: int | None
    sort_order: int
    is_active: bool
    # How many club-seasons are filed against it. A competition nobody entered
    # can be renamed freely; one with a season behind it cannot.
    seasons: int = 0


# --- tenants ----------------------------------------------------------------


@router.get("/tenants", response_model=list[TenantRow], summary="Every tenant")
async def list_tenants(
    ctx: Annotated[RequestContext, Depends(READ)],
    q: Annotated[str | None, Query(max_length=120)] = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
) -> list[TenantRow]:
    async with platform_session(reason="list tenants in the super-admin console") as session:
        stmt = select(Tenant)
        if status_:
            stmt = stmt.where(Tenant.status == status_)
        if q:
            pattern = f"%{q.strip()}%"
            stmt = stmt.where(
                Tenant.legal_name.ilike(pattern)
                | Tenant.trading_name.ilike(pattern)
                | Tenant.slug.ilike(pattern)
            )
        tenants = list(await session.scalars(stmt.order_by(Tenant.created_at.desc())))
        if not tenants:
            return []

        ids = [tenant.id for tenant in tenants]

        club_counts = dict(
            (
                await session.execute(
                    select(Club.tenant_id, func.count(Club.id))
                    .where(Club.tenant_id.in_(ids))
                    .group_by(Club.tenant_id)
                )
            ).all()
        )
        player_counts = dict(
            (
                await session.execute(
                    select(Player.tenant_id, func.count(Player.id))
                    .where(Player.tenant_id.in_(ids), Player.status != "DEPARTED")
                    .group_by(Player.tenant_id)
                )
            ).all()
        )
        plans = {
            row[0]: row[1:]
            for row in (
                await session.execute(
                    select(
                        TenantSubscription.tenant_id,
                        Plan.key,
                        TenantSubscription.status,
                        TenantSubscription.trial_ends_at,
                    )
                    .join(PlanVersion, PlanVersion.id == TenantSubscription.plan_version_id)
                    .join(Plan, Plan.id == PlanVersion.plan_id)
                    .where(TenantSubscription.tenant_id.in_(ids))
                )
            ).all()
        }

        return [
            TenantRow(
                id=tenant.id,
                slug=tenant.slug,
                name=tenant.trading_name or tenant.legal_name,
                status=tenant.status,
                country_code=tenant.country_code,
                default_locale=tenant.default_locale,
                supported_locales=tenant.supported_locales,
                default_currency=tenant.default_currency,
                plan=plans.get(tenant.id, (None, None, None))[0],
                subscription_status=plans.get(tenant.id, (None, None, None))[1],
                trial_ends_at=plans.get(tenant.id, (None, None, None))[2],
                clubs=club_counts.get(tenant.id, 0),
                players=player_counts.get(tenant.id, 0),
                created_at=tenant.created_at,
            )
            for tenant in tenants
        ]


@router.patch("/tenants/{tenant_id}", response_model=TenantRow, summary="Edit a tenant")
async def update_tenant(
    tenant_id: UUID,
    payload: TenantUpdate,
    ctx: Annotated[RequestContext, Depends(MANAGE)],
) -> TenantRow:
    """Suspend, reopen, or change a tenant's languages.

    Suspending is not deleting: `CLOSED` is the terminal state and it is what
    stops a login, while `SUSPENDED` leaves the tenant readable so the club can
    be talked to about whatever caused it.
    """
    changes = payload.model_dump(exclude_unset=True)

    async with platform_session(
        reason=f"edit tenant {tenant_id} from the super-admin console"
    ) as session:
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            raise NotFound(object_type="tenant", object_id=str(tenant_id))

        if "supported_locales" in changes:
            locales = [normalise(code) for code in changes["supported_locales"]]
            unknown = sorted(set(locales) - LOCALE_CODES)
            if unknown:
                raise ValidationFailed(
                    f"The platform does not ship {', '.join(unknown)} yet.",
                    field="supported_locales",
                )
            if not locales:
                raise ValidationFailed(
                    "A tenant needs at least one language.", field="supported_locales"
                )
            changes["supported_locales"] = locales

        default_locale = changes.get("default_locale", tenant.default_locale)
        supported = changes.get("supported_locales", tenant.supported_locales)
        if normalise(default_locale) not in supported:
            raise ValidationFailed(
                "The default language has to be one the tenant publishes in.",
                field="default_locale",
            )

        before = {field: getattr(tenant, field) for field in changes}
        for field, value in changes.items():
            setattr(tenant, field, value)

        AuditService(session).record(
            ctx,
            action="platform.tenant.update",
            object_type="tenant",
            object_id=tenant.id,
            before=before,
            after=changes,
        )
        await session.flush()

    return next(row for row in await list_tenants(ctx) if row.id == tenant_id)


# --- plans ------------------------------------------------------------------


@router.get("/plans", response_model=list[PlanOut], summary="The plan catalogue")
async def list_plans(ctx: Annotated[RequestContext, Depends(READ)]) -> list[PlanOut]:
    async with platform_session(reason="read the plan catalogue") as session:
        rows = (
            await session.execute(
                select(Plan, PlanVersion)
                .join(PlanVersion, PlanVersion.plan_id == Plan.id)
                .order_by(Plan.sort_order, PlanVersion.version.desc())
            )
        ).all()

        # Newest version per plan: versions are append-only, so "current" is the
        # highest rather than a flag somebody has to remember to move.
        latest: dict[UUID, tuple[Plan, PlanVersion]] = {}
        for plan, version in rows:
            if plan.id not in latest:
                latest[plan.id] = (plan, version)

        features: dict[UUID, list[PlanFeature]] = {}
        for feature in await session.scalars(
            select(PlanFeature).where(
                PlanFeature.plan_version_id.in_([v.id for _, v in latest.values()])
            )
        ):
            features.setdefault(feature.plan_version_id, []).append(feature)

        return [
            PlanOut(
                id=plan.id,
                key=plan.key,
                name=plan.name,
                tier=plan.tier,
                version=version.version,
                features=[
                    PlanFeatureOut(
                        feature_key=f.feature_key,
                        enabled=f.enabled,
                        limit_value=f.limit_value,
                    )
                    for f in sorted(features.get(version.id, []), key=lambda f: f.feature_key)
                ],
            )
            for plan, version in latest.values()
        ]


@router.put(
    "/tenants/{tenant_id}/subscription",
    response_model=TenantRow,
    summary="Put a tenant on a plan",
)
async def set_subscription(
    tenant_id: UUID,
    payload: SubscriptionIn,
    ctx: Annotated[RequestContext, Depends(MANAGE)],
) -> TenantRow:
    async with platform_session(
        reason=f"move tenant {tenant_id} onto plan {payload.plan_key}"
    ) as session:
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            raise NotFound(object_type="tenant", object_id=str(tenant_id))

        version = await session.scalar(
            select(PlanVersion)
            .join(Plan, Plan.id == PlanVersion.plan_id)
            .where(Plan.key == payload.plan_key)
            .order_by(PlanVersion.version.desc())
            .limit(1)
        )
        if version is None:
            raise NotFound(object_type="plan", object_id=payload.plan_key)

        existing = await session.scalar(
            select(TenantSubscription).where(TenantSubscription.tenant_id == tenant_id)
        )
        before = (
            {"plan_version_id": str(existing.plan_version_id), "status": existing.status}
            if existing
            else {}
        )

        if existing is None:
            session.add(
                TenantSubscription(
                    id=new_id(),
                    tenant_id=tenant_id,
                    plan_version_id=version.id,
                    status=payload.status,
                    currency=tenant.default_currency,
                    current_period_start=datetime.now(UTC),
                )
            )
        else:
            existing.plan_version_id = version.id
            existing.status = payload.status

        AuditService(session).record(
            ctx,
            action="platform.subscription.change",
            object_type="tenant",
            object_id=tenant_id,
            before=before,
            after={"plan": payload.plan_key, "status": payload.status},
        )
        await session.flush()

    # After the transaction: entitlements are cached per tenant behind a version
    # counter, and invalidating before the commit caches the old answer again.
    await invalidate_entitlements(tenant_id)
    return next(row for row in await list_tenants(ctx) if row.id == tenant_id)


# --- impersonation ----------------------------------------------------------


@router.post(
    "/tenants/{tenant_id}/impersonate",
    response_model=ImpersonationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Enter a tenant as support",
)
async def impersonate(
    tenant_id: UUID,
    payload: ImpersonationIn,
    ctx: Annotated[RequestContext, Depends(IMPERSONATE)],
) -> ImpersonationOut:
    """Grant yourself a time-limited role in someone else's tenant.

    A real `role_assignment` with a `valid_until`, not a flag on the session:
    the request path already refuses a tenant the caller holds no live role in,
    so the safe way to get in is to genuinely be in — visibly, revocably, and
    with the same expiry checks as every other grant.

    CLUB_ADMIN rather than TENANT_OWNER on purpose. Support needs to see what
    the club sees; it does not need to grant roles or change the subscription,
    and an impersonation that can hand out permissions is an impersonation that
    can hide itself.
    """
    now = datetime.now(UTC)
    minutes = min(timedelta(minutes=payload.minutes), IMPERSONATION_MAX)
    expires = now + (minutes or IMPERSONATION_DEFAULT)

    async with platform_session(
        reason=f"impersonate tenant {tenant_id}: {payload.reason}"
    ) as session:
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            raise NotFound(object_type="tenant", object_id=str(tenant_id))
        if tenant.status == "CLOSED":
            raise ValidationFailed("This tenant is closed.", field="status")

        role = await session.scalar(select(Role).where(Role.key == "CLUB_ADMIN"))
        if role is None:
            raise ValidationFailed("The platform is not fully configured yet.")

        existing = await session.scalar(
            select(RoleAssignment).where(
                RoleAssignment.user_id == ctx.actor_id,
                RoleAssignment.role_id == role.id,
                RoleAssignment.tenant_id == tenant_id,
                RoleAssignment.club_id.is_(None),
                RoleAssignment.team_id.is_(None),
            )
        )
        if existing is not None:
            # Re-entering, or extending. The unique constraint covers this
            # combination, so it has to be an update rather than a second row.
            existing.valid_from = now
            existing.valid_until = expires
            existing.revoked_at = None
            existing.revoke_reason = None
            existing.granted_by = ctx.actor_id
        else:
            session.add(
                RoleAssignment(
                    id=new_id(),
                    user_id=ctx.actor_id,
                    role_id=role.id,
                    tenant_id=tenant_id,
                    valid_from=now,
                    valid_until=expires,
                    granted_by=ctx.actor_id,
                )
            )

        AuditService(session).record(
            ctx,
            action="platform.impersonate.start",
            object_type="tenant",
            object_id=tenant_id,
            after={"reason": payload.reason, "expires_at": expires.isoformat()},
        )
        await session.flush()

    # The caller's own permissions just changed.
    from app.authz.service import PermissionResolver

    async with platform_session(reason="refresh the impersonator's permissions") as session:
        await PermissionResolver(session).invalidate(ctx.actor_id)

    return ImpersonationOut(
        tenant_id=tenant_id,
        tenant_name=tenant.trading_name or tenant.legal_name,
        expires_at=expires,
        role="CLUB_ADMIN",
    )


@router.delete(
    "/tenants/{tenant_id}/impersonate",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Leave a tenant",
)
async def stop_impersonating(
    tenant_id: UUID,
    ctx: Annotated[RequestContext, Depends(IMPERSONATE)],
) -> None:
    now = datetime.now(UTC)
    async with platform_session(reason=f"end impersonation of tenant {tenant_id}") as session:
        grants = await session.scalars(
            select(RoleAssignment).where(
                RoleAssignment.user_id == ctx.actor_id,
                RoleAssignment.tenant_id == tenant_id,
                RoleAssignment.revoked_at.is_(None),
            )
        )
        for grant in grants:
            grant.revoked_at = now
            grant.revoke_reason = "impersonation ended"

        AuditService(session).record(
            ctx,
            action="platform.impersonate.end",
            object_type="tenant",
            object_id=tenant_id,
        )
        await session.flush()

    from app.authz.service import PermissionResolver

    async with platform_session(reason="refresh the impersonator's permissions") as session:
        await PermissionResolver(session).invalidate(ctx.actor_id)


# --- competition curation ---------------------------------------------------


@router.get("/competitions", response_model=list[CompetitionOut], summary="Curate competitions")
async def list_all_competitions(
    ctx: Annotated[RequestContext, Depends(READ)],
) -> list[CompetitionOut]:
    """Every competition, active or not — the club-facing list hides the rest."""
    from app.competitions.models import CompetitionSeason

    async with platform_session(reason="review the competition catalogue") as session:
        rows = (
            await session.execute(
                select(Competition, Country.code)
                .join(Country, Country.id == Competition.country_id, isouter=True)
                .order_by(Competition.sort_order, Competition.name)
            )
        ).all()

        counts = dict(
            (
                await session.execute(
                    select(
                        CompetitionSeason.competition_id, func.count(CompetitionSeason.id)
                    ).group_by(CompetitionSeason.competition_id)
                )
            ).all()
        )

        return [
            CompetitionOut(
                id=competition.id,
                country_code=code,
                key=competition.key,
                name=competition.name,
                short_name=competition.short_name,
                format=competition.format,
                scope=competition.scope,
                tier=competition.tier,
                sort_order=competition.sort_order,
                is_active=competition.is_active,
                seasons=counts.get(competition.id, 0),
            )
            for competition, code in rows
        ]


@router.post(
    "/competitions",
    response_model=CompetitionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a competition",
)
async def create_competition(
    payload: CompetitionIn,
    ctx: Annotated[RequestContext, Depends(CURATE)],
) -> CompetitionOut:
    """Reference data every tenant reads, so only the platform writes it.

    Two clubs in the same division have to be choosing the same division; a
    competition a club could invent for itself would make the shared table
    meaningless.
    """
    async with platform_session(reason=f"add competition {payload.key}") as session:
        country = None
        if payload.country_code:
            country = await session.scalar(
                select(Country).where(Country.code == payload.country_code.upper())
            )
            if country is None:
                raise NotFound(object_type="country", object_id=payload.country_code)

        duplicate = await session.scalar(
            select(Competition.id).where(Competition.key == payload.key)
        )
        if duplicate is not None:
            raise Conflict("There is already a competition with that key.", field="key")

        competition = Competition(
            country_id=country.id if country else None,
            key=payload.key,
            name=payload.name,
            short_name=payload.short_name,
            format=payload.format,
            scope=payload.scope,
            tier=payload.tier,
            sort_order=payload.sort_order,
            is_active=payload.is_active,
        )
        session.add(competition)
        await session.flush()

        AuditService(session).record(
            ctx,
            action="platform.competition.create",
            object_type="competition",
            object_id=competition.id,
            after={"key": competition.key, "name": competition.name},
        )
        result = CompetitionOut(
            id=competition.id,
            country_code=country.code if country else None,
            key=competition.key,
            name=competition.name,
            short_name=competition.short_name,
            format=competition.format,
            scope=competition.scope,
            tier=competition.tier,
            sort_order=competition.sort_order,
            is_active=competition.is_active,
            seasons=0,
        )
        await session.flush()
    return result


@router.patch(
    "/competitions/{competition_id}",
    response_model=CompetitionOut,
    summary="Edit a competition",
)
async def update_competition(
    competition_id: UUID,
    payload: CompetitionIn,
    ctx: Annotated[RequestContext, Depends(CURATE)],
) -> CompetitionOut:
    async with platform_session(reason=f"edit competition {competition_id}") as session:
        competition = await session.get(Competition, competition_id)
        if competition is None:
            raise NotFound(object_type="competition", object_id=str(competition_id))

        country = None
        if payload.country_code:
            country = await session.scalar(
                select(Country).where(Country.code == payload.country_code.upper())
            )
            if country is None:
                raise NotFound(object_type="country", object_id=payload.country_code)

        before = {
            "name": competition.name,
            "is_active": competition.is_active,
            "tier": competition.tier,
        }
        competition.country_id = country.id if country else None
        competition.key = payload.key
        competition.name = payload.name
        competition.short_name = payload.short_name
        competition.format = payload.format
        competition.scope = payload.scope
        competition.tier = payload.tier
        competition.sort_order = payload.sort_order
        competition.is_active = payload.is_active

        AuditService(session).record(
            ctx,
            action="platform.competition.update",
            object_type="competition",
            object_id=competition.id,
            before=before,
            after=payload.model_dump(),
        )
        await session.flush()

    return next(row for row in await list_all_competitions(ctx) if row.id == competition_id)
