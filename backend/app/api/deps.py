"""FastAPI dependencies.

The evaluation order is fixed and matters (docs/architecture/06-authorization.md):

    1. authenticated?        → 401
    2. tenant context valid? → 404 / 400
    3. feature entitled?     → 402
    4. permission at scope?  → 403
    5. object inside scope?  → 404  (handled in the service)
    6. sensitive → step-up?  → 401
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.middleware import enlist
from app.audit.service import record_access
from app.authz.permissions import EffectivePermissions, get_permission
from app.authz.scope import Scope, ScopeLevel
from app.authz.service import PermissionResolver, ScopeFilter, scope_filter_for
from app.billing.features import Feature, get_feature
from app.billing.service import EntitlementService, unlimited_entitlements
from app.core.context import (
    Principal,
    RequestContext,
    current_request_id,
    reset_tenant_id,
    set_tenant_id,
)
from app.core.db import SessionFactory, bind_tenant, bind_user, tenant_session
from app.core.errors import (
    PermissionDenied,
    StepUpRequired,
    TenantContextMissing,
    TenantSuspended,
    Unauthenticated,
)
from app.identity.service import IdentityService
from app.identity.tokens import verify_access_token
from app.tenants.models import Tenant

log = structlog.get_logger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)

STEP_UP_MAX_AGE = timedelta(minutes=15)


async def bootstrap_session(request: Request) -> AsyncIterator[AsyncSession]:
    """A session with no tenant bound, for identity work only.

    Only global tables (user_account, role_assignment, tenant, role) are
    readable here — every tenant-scoped table returns zero rows, because the
    RLS variable is empty. That is the intended failure mode.

    It commits, because sign-in is not purely a read: the last-login stamp, the
    mirrored account row and the activation of a tenant whose owner has just
    proved their address all happen here. Rolling back unconditionally — as
    this did — discarded them silently, which is the worst shape a bug can
    take: the code is correct, the log line even fires, and nothing persists.
    """
    async with SessionFactory() as session:
        await session.begin()
        enlist(request, session)
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            # Usually already committed by `UnitOfWorkMiddleware`, before the
            # response went out. This remains the backstop for the paths it
            # deliberately leaves alone — a route that returns a 4xx of its own
            # accord, and any caller that is not an HTTP request.
            if session.in_transaction():
                await session.commit()


async def get_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(bootstrap_session)],
) -> Principal:
    if credentials is None or not credentials.credentials:
        raise Unauthenticated()

    claims = await verify_access_token(credentials.credentials)

    identity = IdentityService(session)
    user = await identity.upsert_from_token(claims)
    is_platform = await identity.has_platform_role(user.id)
    if user.is_platform_user != is_platform:
        user.is_platform_user = is_platform
    await session.commit()

    return Principal(
        user_id=user.id,
        subject_id=user.subject_id,
        email=user.email,
        is_platform_user=is_platform,
        auth_time=claims.auth_time,
        amr=claims.amr,
        acr=claims.acr,
    )


async def get_context(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[AsyncSession, Depends(bootstrap_session)],
    x_tenant_id: Annotated[UUID | None, Header(alias="X-Tenant-Id")] = None,
) -> AsyncIterator[RequestContext]:
    """Resolve tenant and permissions, then bind the tenant for the request.

    A tenant id supplied by the client is only ever a *request*: it is checked
    against the user's live role assignments before it becomes context.
    """
    # The `tenant` policy admits rows this user holds a role in; without the
    # binding the membership query returns nothing and login is impossible.
    await bind_user(session, principal.user_id)

    # After binding, not before: the `tenant` policy admits rows the *bound*
    # user holds a role in, so this query sees nothing until `app.user_id` is
    # set. Running it earlier silently activated nobody.
    await IdentityService(session).activate_pending_tenants(principal.user_id)

    identity = IdentityService(session)
    memberships = await identity.tenant_memberships(principal.user_id)
    by_id = {t.id: t for t in memberships}

    tenant: Tenant | None = None
    if x_tenant_id is not None:
        tenant = by_id.get(x_tenant_id)
        if tenant is None:
            # Not "forbidden" — as far as this caller is concerned it does not exist.
            raise TenantContextMissing("Unknown tenant for this account.")
    elif len(memberships) == 1:
        tenant = memberships[0]
    elif not principal.is_platform_user:
        raise TenantContextMissing(
            "Specify a tenant with the X-Tenant-Id header.",
            available=[str(t.id) for t in memberships],
        )

    if tenant is not None and tenant.status == "CLOSED":
        raise TenantSuspended()

    resolver = PermissionResolver(session)
    permissions = await resolver.resolve(principal.user_id, tenant.id if tenant else None)

    # Platform operators are not on a plan; tenant work always is.
    if tenant is not None:
        # `tenant_subscription` and `entitlement` are tenant-scoped, so the
        # bootstrap session — which started with no tenant, because it had to
        # work out which tenants this user may act in — must be bound before
        # reading them. Without this the queries return nothing and every
        # tenant silently falls back to the catalogue defaults.
        await bind_tenant(session, tenant.id)
        entitlements = await EntitlementService(session).resolve(tenant.id)
    else:
        entitlements = unlimited_entitlements()

    token = set_tenant_id(tenant.id if tenant else None)
    try:
        yield RequestContext(
            request_id=current_request_id() or "unknown",
            tenant_id=tenant.id if tenant else None,
            principal=principal,
            permissions=permissions,
            entitlements=entitlements,
        )
    finally:
        reset_tenant_id(token)


async def get_db(
    request: Request,
    _: Annotated[RequestContext, Depends(get_context)],
) -> AsyncIterator[AsyncSession]:
    """The request's unit of work, already bound to the resolved tenant.

    Depends on the context so ordering is guaranteed: the tenant is always
    resolved before a session exists.
    """
    async with tenant_session() as session:
        enlist(request, session)
        yield session


Ctx = Annotated[RequestContext, Depends(get_context)]
Db = Annotated[AsyncSession, Depends(get_db)]


class Requires:
    """Declarative authorization for a route.

    Usage:

        ctx: Annotated[RequestContext, Requires("players.player.read")]

    The requested scope is inferred from the `club_id` / `team_id` parameters
    the route already accepts — most specific wins. Pass
    `scope_level=ScopeLevel.PLATFORM` for platform routes, which are the only
    ones that are not tenant-relative.
    """

    def __init__(
        self,
        permission: str,
        *,
        scope_level: ScopeLevel | None = None,
        feature: Feature | str | None = None,
    ) -> None:
        # Both raise at import time for an unknown key, so a typo cannot ship.
        self.permission = get_permission(permission)
        self.scope_level = scope_level
        self.feature = get_feature(feature).key if feature is not None else None

    async def __call__(
        self,
        ctx: Ctx,
        club_id: UUID | None = None,
        team_id: UUID | None = None,
    ) -> RequestContext:
        permissions = ctx.permissions or EffectivePermissions()

        # Entitlement before permission: "your plan does not include this" is a
        # different answer from "you may not do this", and the frontend renders
        # an upgrade prompt rather than an access-denied page.
        if self.feature is not None and ctx.entitlements is not None:
            ctx.entitlements.require(self.feature)

        if self.scope_level is ScopeLevel.PLATFORM:
            requested = Scope.platform()
            if not permissions.is_platform:
                raise PermissionDenied(permission=self.permission.key)
        else:
            # The level follows the most specific identifier the caller gave us.
            requested = Scope.narrowest(ctx.tenant, club_id=club_id, team_id=team_id)

        if not permissions.allows(self.permission.key, requested):
            log.info(
                "permission_denied",
                permission=self.permission.key,
                scope=str(requested),
                user_id=str(ctx.actor.user_id),
            )
            raise PermissionDenied(permission=self.permission.key, scope=str(requested))

        if self.permission.is_sensitive:
            self._require_step_up(ctx)
            # Every sensitive access leaves a record, whether or not the action
            # that follows succeeds. Written in its own transaction so it cannot
            # be rolled back with the request it is observing.
            await record_access(
                ctx,
                action=self.permission.key,
                object_type=self.permission.module,
                context={"scope": str(requested)},
            )

        return ctx

    @staticmethod
    def _require_step_up(ctx: RequestContext) -> None:
        principal = ctx.actor
        if not principal.has_second_factor:
            raise StepUpRequired("This action requires multi-factor authentication.")
        if principal.auth_time is None:
            raise StepUpRequired()
        if datetime.now(UTC) - principal.auth_time > STEP_UP_MAX_AGE:
            raise StepUpRequired("Please re-authenticate to continue.")


def scoped_filter(ctx: RequestContext, permission: str) -> ScopeFilter:
    """Narrow a collection to the rows this caller may actually see."""
    return scope_filter_for(ctx.permissions or EffectivePermissions(), permission, ctx.tenant)
