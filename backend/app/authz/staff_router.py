"""Who works at this club, and what they may touch.

The screen a club administrator uses to give the person who writes the news a
login that reaches the news and nothing else. Every rule that matters lives in
`staff_service`; this file is the shape of the request and the shape of the
answer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select

from app.api.deps import STEP_UP_MAX_AGE, Db, Requires
from app.audit.service import AuditService
from app.authz import staff_service as staff
from app.authz.models import Role, RoleAssignment
from app.authz.role_templates import BY_KEY_TEMPLATE
from app.authz.scope import Scope
from app.core.context import RequestContext
from app.core.errors import NotFound, PermissionDenied, StepUpRequired
from app.identity.keycloak import get_admin
from app.identity.models import Person, UserAccount
from app.teams.models import Team
from app.tenants.models import Club

router = APIRouter(tags=["staff"])

READ = "authz.role.read"
# Staffing a club. The narrower `authz.role.manage` — which is sensitive and
# does demand a second factor — is checked separately, and only when the role
# being handed out could itself hand out roles.
MANAGE = "authz.role.grant"


def _guard_delegation(ctx: RequestContext, role_key: str, scope: Scope) -> None:
    """Stop somebody quietly minting another administrator.

    Adding a coach is ordinary club work. Giving somebody the power to add
    coaches is delegation, and that is the step worth a second factor — so it
    is checked here rather than by gating the whole screen, which only meant a
    club could not staff itself at all.
    """
    template = BY_KEY_TEMPLATE.get(role_key)
    if template is None or "authz.role.manage" not in template.permissions:
        return

    permissions = ctx.permissions
    if permissions is None or not permissions.allows("authz.role.manage", scope):
        raise PermissionDenied(permission="authz.role.manage", scope=str(scope))

    principal = ctx.actor
    if not principal.has_second_factor:
        raise StepUpRequired("Making somebody an administrator requires two-factor.")
    if principal.auth_time is None or datetime.now(UTC) - principal.auth_time > STEP_UP_MAX_AGE:
        raise StepUpRequired("Please re-authenticate to continue.")


class RoleOut(BaseModel):
    key: str
    name: str
    scope_level: str
    description: str
    # False when the caller holds less than the role would grant. Sent so the
    # screen can explain the refusal rather than hide the option and leave
    # somebody wondering where "Academy Director" went.
    grantable: bool


class StaffOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    email: str
    display_name: str
    role_key: str
    role_name: str
    club_id: UUID | None
    team_id: UUID | None
    scope_label: str | None
    # An invitation not yet accepted. The club needs to see this: chasing
    # somebody who never set a password is the commonest support question.
    pending: bool
    last_login_at: datetime | None
    granted_at: datetime | None


class InviteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=2, max_length=48)
    club_id: UUID | None = None
    team_id: UUID | None = None
    # Optional. Left empty, the person gets an invitation link and chooses
    # their own — which is the better path and the default. Supplied, it is a
    # starting password they are forced to change at first sign-in, for the
    # coach who has no working email or is standing in the room.
    temporary_password: str | None = Field(default=None, min_length=10, max_length=128)


class ChangeRoleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(min_length=2, max_length=48)
    club_id: UUID | None = None
    team_id: UUID | None = None


async def _labels(db, tenant_id: UUID) -> dict[UUID, str]:
    """Club and team names, for showing a grant as a person would say it."""
    labels: dict[UUID, str] = {}
    for club in await db.scalars(select(Club).where(Club.tenant_id == tenant_id)):
        labels[club.id] = club.short_name or club.legal_name
    for team in await db.scalars(select(Team).where(Team.tenant_id == tenant_id)):
        labels[team.id] = team.name
    return labels


@router.get("/staff/roles", response_model=list[RoleOut], summary="Roles that can be given")
async def list_roles(
    ctx: Annotated[RequestContext, Depends(Requires(READ))],
    club_id: UUID | None = None,
    team_id: UUID | None = None,
) -> list[RoleOut]:
    """What this caller may hand out, at this scope.

    Scope-dependent by design: the same administrator may be able to appoint a
    coach at one club and not at another, and a list that ignored that would be
    a list of buttons that fail.
    """
    out: list[RoleOut] = []
    for key in staff.invitable_roles():
        template = BY_KEY_TEMPLATE[key]
        try:
            scope = staff.scope_for(key, ctx.tenant, club_id, team_id)
        except Exception:
            # The caller has not chosen a club or team yet; the role is real,
            # it just cannot be evaluated until they do.
            out.append(
                RoleOut(
                    key=key,
                    name=template.name,
                    scope_level=template.scope_level.name,
                    description=template.description,
                    grantable=False,
                )
            )
            continue
        out.append(
            RoleOut(
                key=key,
                name=template.name,
                scope_level=template.scope_level.name,
                description=template.description,
                grantable=staff.may_grant(ctx, key, scope),
            )
        )
    return out


@router.get("/staff", response_model=list[StaffOut], summary="Who works here")
async def list_staff(
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(READ))],
) -> list[StaffOut]:
    assignments = await staff.assignments_in(db, ctx.tenant)
    if not assignments:
        return []

    roles = {
        role.id: role
        for role in await db.scalars(
            select(Role).where(Role.id.in_({a.role_id for a in assignments}))
        )
    }
    user_ids = {a.user_id for a in assignments}
    accounts = {
        account.id: account
        for account in await db.scalars(select(UserAccount).where(UserAccount.id.in_(user_ids)))
    }
    people = {
        person.user_id: person
        for person in await db.scalars(
            select(Person).where(Person.tenant_id == ctx.tenant, Person.user_id.in_(user_ids))
        )
    }
    labels = await _labels(db, ctx.tenant)

    out: list[StaffOut] = []
    for assignment in assignments:
        account = accounts.get(assignment.user_id)
        role = roles.get(assignment.role_id)
        if account is None or role is None:
            continue
        person = people.get(account.id)
        target = assignment.team_id or assignment.club_id
        out.append(
            StaffOut(
                user_id=account.id,
                email=account.email,
                display_name=(person.display_name if person else account.email.split("@")[0]),
                role_key=role.key,
                role_name=role.name,
                club_id=assignment.club_id,
                team_id=assignment.team_id,
                scope_label=labels.get(target) if target else None,
                pending=account.last_login_at is None,
                last_login_at=account.last_login_at,
                granted_at=assignment.valid_from or assignment.created_at,
            )
        )
    return out


@router.post(
    "/staff",
    response_model=StaffOut,
    status_code=status.HTTP_201_CREATED,
    summary="Invite somebody to work here",
)
async def invite(
    payload: InviteIn,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(MANAGE))],
) -> StaffOut:
    """Create the login, the person and the grant.

    The identity provider goes first, as it does in sign-up: a login with no
    grant behind it is a recoverable orphan, while a grant pointing at a login
    that was never created is a broken row that shows up as a staff member
    nobody can be.

    The role is checked *before* anything is created — an escalation attempt
    should not leave an invitation email behind.
    """
    scope = staff.scope_for(payload.role, ctx.tenant, payload.club_id, payload.team_id)
    _guard_delegation(ctx, payload.role, scope)
    if not staff.may_grant(ctx, payload.role, scope):
        from app.core.errors import ValidationFailed

        raise ValidationFailed(
            "You cannot give somebody access you do not have yourself.", field="role"
        )

    club = None
    if payload.club_id is not None:
        club = await db.scalar(
            select(Club).where(Club.tenant_id == ctx.tenant, Club.id == payload.club_id)
        )
        if club is None:
            raise NotFound("That club is not in this workspace.")
    if payload.team_id is not None:
        team = await db.scalar(
            select(Team).where(Team.tenant_id == ctx.tenant, Team.id == payload.team_id)
        )
        if team is None:
            raise NotFound("That team is not in this workspace.")

    created = await get_admin().invite_user(
        email=str(payload.email),
        first_name=payload.first_name,
        last_name=payload.last_name,
        temporary_password=payload.temporary_password,
    )

    account = await db.scalar(
        select(UserAccount).where(UserAccount.subject_id == created.subject_id)
    )
    if account is None:
        account = UserAccount(
            subject_id=created.subject_id,
            email=str(payload.email),
            email_verified=False,
            status="ACTIVE",
        )
        db.add(account)
        await db.flush()

    person = await staff.person_for(
        db,
        tenant_id=ctx.tenant,
        account=account,
        first_name=payload.first_name,
        last_name=payload.last_name,
        locale=club.default_locale if club else None,
    )

    assignment = await staff.grant(
        db,
        ctx,
        user_id=account.id,
        role_key=payload.role,
        club_id=payload.club_id,
        team_id=payload.team_id,
    )

    role = await db.get(Role, assignment.role_id)
    AuditService(db).record(
        ctx,
        action="staff.invited",
        object_type="role_assignment",
        object_id=assignment.id,
        club_id=payload.club_id,
        after={"email": str(payload.email), "role": payload.role},
    )

    labels = await _labels(db, ctx.tenant)
    target = assignment.team_id or assignment.club_id
    return StaffOut(
        user_id=account.id,
        email=account.email,
        display_name=person.display_name,
        role_key=payload.role,
        role_name=role.name if role else payload.role,
        club_id=assignment.club_id,
        team_id=assignment.team_id,
        scope_label=labels.get(target) if target else None,
        pending=account.last_login_at is None,
        last_login_at=account.last_login_at,
        granted_at=assignment.valid_from,
    )


@router.put("/staff/{user_id}/role", response_model=StaffOut, summary="Change what they do")
async def change_role(
    user_id: UUID,
    payload: ChangeRoleIn,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(MANAGE))],
) -> StaffOut:
    """Replace their grants in this tenant with one new one.

    Replace rather than add: this screen answers "what is this person's job
    here", and a UI that quietly accumulated roles would leave somebody moved
    from head coach to kit manager still holding the squad.
    """
    account = await db.get(UserAccount, user_id)
    if account is None:
        raise NotFound("That person does not work here.")

    scope = staff.scope_for(payload.role, ctx.tenant, payload.club_id, payload.team_id)
    _guard_delegation(ctx, payload.role, scope)
    if not staff.may_grant(ctx, payload.role, scope):
        from app.core.errors import ValidationFailed

        raise ValidationFailed(
            "You cannot give somebody access you do not have yourself.", field="role"
        )

    before = await staff.revoke(db, ctx, user_id=user_id, reason="Role changed")
    assignment = await staff.grant(
        db,
        ctx,
        user_id=user_id,
        role_key=payload.role,
        club_id=payload.club_id,
        team_id=payload.team_id,
    )

    role = await db.get(Role, assignment.role_id)
    AuditService(db).record(
        ctx,
        action="staff.role_changed",
        object_type="role_assignment",
        object_id=assignment.id,
        club_id=payload.club_id,
        before={"grants": before},
        after={"role": payload.role},
    )

    person = await db.scalar(
        select(Person).where(Person.tenant_id == ctx.tenant, Person.user_id == user_id)
    )
    labels = await _labels(db, ctx.tenant)
    target = assignment.team_id or assignment.club_id
    return StaffOut(
        user_id=user_id,
        email=account.email,
        display_name=person.display_name if person else account.email.split("@")[0],
        role_key=payload.role,
        role_name=role.name if role else payload.role,
        club_id=assignment.club_id,
        team_id=assignment.team_id,
        scope_label=labels.get(target) if target else None,
        pending=account.last_login_at is None,
        last_login_at=account.last_login_at,
        granted_at=assignment.valid_from,
    )


@router.post(
    "/staff/{user_id}/invitation",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Send the invitation again",
)
async def resend(
    user_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(MANAGE))],
) -> None:
    """For the invitation that went to a spam folder."""
    account = await db.get(UserAccount, user_id)
    if account is None:
        raise NotFound("That person does not work here.")

    held = await db.scalar(
        select(RoleAssignment.id).where(
            RoleAssignment.user_id == user_id,
            RoleAssignment.tenant_id == ctx.tenant,
            RoleAssignment.revoked_at.is_(None),
        )
    )
    if held is None:
        raise NotFound("That person does not work here.")

    await get_admin().send_invitation_email(account.subject_id)


@router.delete(
    "/staff/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove their access",
)
async def remove(
    user_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(MANAGE))],
) -> None:
    """Ends the job, not the login.

    The person keeps their account — it is theirs, they may support this club
    or work at another one — and loses every grant this tenant gave them.
    """
    revoked = await staff.revoke(db, ctx, user_id=user_id, reason="Removed by the club")
    AuditService(db).record(
        ctx,
        action="staff.removed",
        object_type="user_account",
        object_id=user_id,
        before={"grants": revoked},
    )
