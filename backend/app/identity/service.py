"""User provisioning and tenant membership."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz.models import RoleAssignment
from app.identity.models import UserAccount
from app.identity.tokens import TokenClaims
from app.tenants.models import Tenant

log = structlog.get_logger(__name__)


class IdentityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_from_token(self, claims: TokenClaims) -> UserAccount:
        """Mirror the Keycloak identity locally, creating it on first sight.

        The mirror exists for referential integrity and joins. It is never
        authoritative for authentication state.
        """
        user = await self.session.scalar(
            select(UserAccount).where(UserAccount.subject_id == claims.subject_id)
        )
        if user is None:
            user = UserAccount(
                subject_id=claims.subject_id,
                email=claims.email,
                email_verified=claims.email_verified,
                mfa_enabled=bool(claims.amr & {"otp", "mfa", "hwk", "webauthn"}),
            )
            self.session.add(user)
            await self.session.flush()
            log.info("user_account_created", user_id=str(user.id))
        else:
            user.email = claims.email
            user.email_verified = claims.email_verified

        user.last_login_at = datetime.now(UTC)
        return user

    async def tenant_memberships(self, user_id: UUID) -> list[Tenant]:
        """Tenants this user actually holds a live role in.

        This is the allow-list against which a requested tenant is validated.
        A tenant id arriving from a client is a *request*, never an authority.

        "Live" means unrevoked *and* in date. The permission resolver has always
        honoured `valid_until`; this did not, so a lapsed grant left the holder
        able to enter the tenant with no permissions inside it — which is the
        wrong shape of refusal, and would have made a time-limited
        impersonation not actually time-limited.
        """
        now = datetime.now(UTC)
        stmt = (
            select(Tenant)
            .join(RoleAssignment, RoleAssignment.tenant_id == Tenant.id)
            .where(
                RoleAssignment.user_id == user_id,
                RoleAssignment.revoked_at.is_(None),
                or_(
                    RoleAssignment.valid_from.is_(None),
                    RoleAssignment.valid_from <= now,
                ),
                or_(
                    RoleAssignment.valid_until.is_(None),
                    RoleAssignment.valid_until > now,
                ),
                Tenant.status.in_(("ACTIVE", "PENDING", "SUSPENDED")),
            )
            .distinct()
            .order_by(Tenant.legal_name)
        )
        return list(await self.session.scalars(stmt))

    async def has_platform_role(self, user_id: UUID) -> bool:
        now = datetime.now(UTC)
        stmt = select(RoleAssignment.id).where(
            RoleAssignment.user_id == user_id,
            RoleAssignment.tenant_id.is_(None),
            RoleAssignment.revoked_at.is_(None),
            or_(
                RoleAssignment.valid_until.is_(None),
                RoleAssignment.valid_until > now,
            ),
        )
        return (await self.session.scalar(stmt)) is not None

    async def activate_pending_tenants(self, user_id: UUID) -> None:
        """Turn a signed-up tenant on once its owner's address is proven.

        Registration leaves the tenant `PENDING` deliberately: the address is
        claimed but unproven, and an unproven club must not have a live public
        website. Nothing propagates the proof back — verification happens inside
        the identity provider, which has no idea this database exists.

        So it is resolved on the way in, and by *current state* rather than by
        watching for the change: reacting only to the transition misses an
        account that was already verified when its row was written, or one whose
        activation failed once and would then stay pending forever.

        It runs on the platform session because row-level security is right to
        refuse it otherwise — a tenant cannot promote itself out of PENDING, and
        at this point in the request there is no tenant bound anyway.
        """
        from sqlalchemy import select as _select

        from app.authz.models import Role, RoleAssignment
        from app.core.db import platform_session
        from app.tenants.models import Tenant

        account = await self.session.get(UserAccount, user_id)
        if account is None or not account.email_verified:
            return

        async with platform_session(
            reason="activate a tenant whose owner has verified their address",
            routine=True,
        ) as session:
            pending = await session.scalars(
                _select(Tenant)
                .join(RoleAssignment, RoleAssignment.tenant_id == Tenant.id)
                .join(Role, Role.id == RoleAssignment.role_id)
                .where(
                    RoleAssignment.user_id == user_id,
                    RoleAssignment.revoked_at.is_(None),
                    Role.key == "TENANT_OWNER",
                    Tenant.status == "PENDING",
                )
            )
            for tenant in pending:
                tenant.status = "ACTIVE"
                log.info("tenant_activated", tenant_id=str(tenant.id), slug=tenant.slug)
