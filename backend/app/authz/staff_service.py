"""Giving somebody a job at the club.

A club runs on volunteers and part-timers: the person who writes the news, the
U15 coach, the physio. Each needs a login and exactly one job's worth of access
— which is what this module is for, and why it is careful about two things.

**Nobody may grant what they do not hold.** The escalation guard is the whole
point of the file: a Club Administrator inviting a Tenant Owner would hand the
tenant away, and "the UI only offers three roles" is not a control. Every grant
is checked against the granter's own effective permissions, at the scope they
hold them.

**An invitation is not a password.** A club administrator never chooses, sees
or sets somebody else's credential. The login is created with none at all and
the invitee sets one through Keycloak, on a page this application never renders.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz.models import Role, RoleAssignment
from app.authz.role_templates import BY_KEY_TEMPLATE
from app.authz.scope import Scope, ScopeLevel
from app.core.context import RequestContext
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.ids import new_id
from app.identity.models import Person, UserAccount

log = structlog.get_logger(__name__)

# Roles a club never grants from this screen.
#
# `TENANT_OWNER` is excluded because handing over the tenant is not staffing —
# it is succession, and it belongs in settings with its own confirmation.
# Platform roles are excluded because a tenant may not mint one at all.
NOT_INVITABLE = frozenset({"TENANT_OWNER", "SUPER_ADMIN", "PLATFORM_SUPPORT"})


def invitable_roles() -> list[str]:
    return [
        template.key
        for template in BY_KEY_TEMPLATE.values()
        if template.key not in NOT_INVITABLE and template.scope_level is not ScopeLevel.PLATFORM
    ]


def scope_for(
    role_key: str, tenant_id: UUID, club_id: UUID | None, team_id: UUID | None
) -> Scope:
    """The scope a role must be granted at, and the arguments it needs.

    A team-level role without a team is not a narrower grant, it is a broader
    one: it would silently become club-wide. So the scope is derived from the
    role's own declared level and the missing identifier is an error, not a
    default.
    """
    template = BY_KEY_TEMPLATE.get(role_key)
    if template is None:
        raise ValidationFailed("That role does not exist.", field="role")

    level = template.scope_level
    if level is ScopeLevel.TEAM:
        if team_id is None:
            raise ValidationFailed("Choose a team for this role.", field="team_id")
        return Scope.team(tenant_id, club_id, team_id)
    if level is ScopeLevel.CLUB:
        if club_id is None:
            raise ValidationFailed("Choose a club for this role.", field="club_id")
        return Scope.club(tenant_id, club_id)
    return Scope.tenant(tenant_id)


def may_grant(ctx: RequestContext, role_key: str, scope: Scope) -> bool:
    """Can this caller hand out this role, here?

    True only when every permission the role carries is one the caller already
    holds at a scope containing the target scope. That single rule covers all
    the cases a list of forbidden combinations would miss: a club admin cannot
    invent a tenant-wide finance manager, a head coach cannot promote somebody
    to academy director, and nobody can grant themselves an upgrade by
    inviting an alias of their own address.
    """
    if role_key in NOT_INVITABLE:
        return False

    template = BY_KEY_TEMPLATE.get(role_key)
    permissions = ctx.permissions
    if template is None or permissions is None:
        return False
    if permissions.is_platform:
        return True

    return all(permissions.allows(key, scope) for key in template.permissions)


async def _role(session: AsyncSession, key: str) -> Role:
    role = await session.scalar(select(Role).where(Role.key == key))
    if role is None:
        # Role templates are reference data seeded at deploy time.
        raise ValidationFailed("The platform is not fully configured yet.")
    return role


def _live() -> tuple:
    now = datetime.now(UTC)
    return (
        RoleAssignment.revoked_at.is_(None),
        or_(RoleAssignment.valid_from.is_(None), RoleAssignment.valid_from <= now),
        or_(RoleAssignment.valid_until.is_(None), RoleAssignment.valid_until > now),
    )


async def assignments_in(session: AsyncSession, tenant_id: UUID) -> list[RoleAssignment]:
    """Every live grant in this tenant, newest first."""
    return list(
        await session.scalars(
            select(RoleAssignment)
            .where(RoleAssignment.tenant_id == tenant_id, *_live())
            .order_by(RoleAssignment.created_at.desc())
        )
    )


async def grant(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    user_id: UUID,
    role_key: str,
    club_id: UUID | None,
    team_id: UUID | None,
) -> RoleAssignment:
    """Give one person one job. Idempotent for an identical grant."""
    scope = scope_for(role_key, ctx.tenant, club_id, team_id)
    if not may_grant(ctx, role_key, scope):
        # Deliberately a refusal to *grant*, not a 403 on the request: the
        # caller may staff this club, just not with this much power.
        raise ValidationFailed(
            "You cannot give somebody access you do not have yourself.", field="role"
        )

    role = await _role(session, role_key)
    # `IS NULL` rather than `= NULL`: the unique constraint treats nulls as
    # equal (`NULLS NOT DISTINCT`), so the lookup that guards it has to as well
    # or an identical grant would insert and then violate.
    same_club = (
        RoleAssignment.club_id.is_(None)
        if club_id is None
        else RoleAssignment.club_id == club_id
    )
    same_team = (
        RoleAssignment.team_id.is_(None)
        if team_id is None
        else RoleAssignment.team_id == team_id
    )
    existing = await session.scalar(
        select(RoleAssignment).where(
            RoleAssignment.user_id == user_id,
            RoleAssignment.role_id == role.id,
            RoleAssignment.tenant_id == ctx.tenant,
            same_club,
            same_team,
        )
    )
    if existing is not None:
        if existing.revoked_at is None:
            return existing
        # Re-hiring somebody: reinstate the row rather than write a second one,
        # so the unique grant constraint stays true and the history reads as
        # one relationship rather than two.
        existing.revoked_at = None
        existing.revoke_reason = None
        existing.valid_from = datetime.now(UTC)
        existing.granted_by = ctx.actor_id
        return existing

    assignment = RoleAssignment(
        id=new_id(),
        user_id=user_id,
        role_id=role.id,
        tenant_id=ctx.tenant,
        club_id=club_id,
        team_id=team_id,
        valid_from=datetime.now(UTC),
        granted_by=ctx.actor_id,
    )
    session.add(assignment)
    await session.flush()
    return assignment


async def revoke(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    user_id: UUID,
    reason: str | None = None,
) -> int:
    """End somebody's access to this tenant.

    Their login survives — it is theirs, not the club's, and they may be a
    supporter here or staff somewhere else. What ends is every grant this
    tenant made them.
    """
    if user_id == ctx.actor_id:
        # Not paternalism: an owner who removes their own last role locks the
        # tenant, and the recovery involves us.
        raise ValidationFailed("You cannot remove your own access.", field="user_id")

    live = list(
        await session.scalars(
            select(RoleAssignment).where(
                RoleAssignment.user_id == user_id,
                RoleAssignment.tenant_id == ctx.tenant,
                RoleAssignment.revoked_at.is_(None),
            )
        )
    )
    if not live:
        raise NotFound("That person does not work here.")

    owner_role = await _role(session, "TENANT_OWNER")
    if any(a.role_id == owner_role.id for a in live):
        remaining = await session.scalar(
            select(RoleAssignment.id).where(
                RoleAssignment.tenant_id == ctx.tenant,
                RoleAssignment.role_id == owner_role.id,
                RoleAssignment.user_id != user_id,
                *_live(),
            )
        )
        if remaining is None:
            raise Conflict("A club must always have at least one owner.")

    now = datetime.now(UTC)
    for assignment in live:
        assignment.revoked_at = now
        assignment.revoke_reason = reason

    log.info(
        "staff_access_revoked",
        user_id=str(user_id),
        tenant_id=str(ctx.tenant),
        grants=len(live),
    )
    return len(live)


async def person_for(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    account: UserAccount,
    first_name: str,
    last_name: str,
    locale: str | None,
) -> Person:
    """The club's record of this human, created if this is their first job here.

    Staff are people the club holds records about, so they get a `person` row
    like anybody else — which is also what makes a coach appear in the same
    directory as the players they coach.
    """
    person = await session.scalar(
        select(Person).where(Person.tenant_id == tenant_id, Person.user_id == account.id)
    )
    if person is not None:
        return person

    person = Person(
        id=new_id(),
        tenant_id=tenant_id,
        user_id=account.id,
        first_name=first_name,
        last_name=last_name,
        display_name=f"{first_name} {last_name}".strip(),
        email=account.email,
        preferred_locale=locale,
        source="STAFF_ENTRY",
    )
    session.add(person)
    await session.flush()
    return person
