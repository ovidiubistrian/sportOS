"""System role templates.

Shipped as data, cloneable per tenant. Two invariants are enforced in the
service layer and tested:

  * a tenant role can never carry a platform permission;
  * a tenant must always retain at least one TENANT_OWNER.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.authz.permissions import BY_KEY
from app.authz.scope import ScopeLevel


@dataclass(frozen=True, slots=True)
class RoleTemplate:
    key: str
    name: str
    scope_level: ScopeLevel
    permissions: tuple[str, ...]
    description: str = ""


_READ_ONLY_CLUB = (
    "clubs.club.read",
    "teams.team.read",
    "people.person.read",
    "players.player.read",
    "staff.profile.read",
    "training.session.read",
)

_COACH = (
    "clubs.club.read",
    "teams.team.read",
    "people.person.read",
    "players.player.read",
    "players.document.read",
    "training.session.read",
    "training.session.manage",
    "training.attendance.record",
    "development.evaluation.read",
    "development.evaluation.manage",
)

TEMPLATES: tuple[RoleTemplate, ...] = (
    # --- platform ---------------------------------------------------------
    RoleTemplate(
        "SUPER_ADMIN",
        "Platform Super Admin",
        ScopeLevel.PLATFORM,
        (
            "platform.tenant.read",
            "platform.tenant.manage",
            "platform.impersonate",
            "platform.competition.manage",
            "billing.subscription.read",
            "billing.subscription.manage",
        ),
        "Full platform administration. MFA is mandatory and cannot be disabled.",
    ),
    RoleTemplate(
        "PLATFORM_SUPPORT",
        "Platform Support",
        ScopeLevel.PLATFORM,
        ("platform.tenant.read", "platform.impersonate"),
        "Tenant metadata plus time-limited, audited impersonation. "
        "No tenant business data by default.",
    ),
    # --- tenant / club ----------------------------------------------------
    RoleTemplate(
        "TENANT_OWNER",
        "Tenant Owner",
        ScopeLevel.TENANT,
        tuple(k for k, p in BY_KEY.items() if not k.startswith("platform.")),
        "Everything within the tenant. Only a Tenant Owner may grant this role.",
    ),
    RoleTemplate(
        "CLUB_ADMIN",
        "Club Administrator",
        ScopeLevel.CLUB,
        (
            *_READ_ONLY_CLUB,
            # The coaching side of the club, because a club administrator
            # appoints coaches and team managers — and under the rule that
            # nobody may grant what they do not hold, an administrator without
            # these could not staff their own club. Medical is deliberately
            # still absent: appointing a physio is not the same as reading a
            # diagnosis.
            *_COACH,
            "clubs.club.update",
            "clubs.season.manage",
            "teams.team.manage",
            "people.person.manage",
            "players.player.create",
            "players.player.update",
            "players.player.delete",
            "players.document.manage",
            "staff.profile.manage",
            "authz.role.read",
            "authz.role.grant",
            "authz.role.manage",
            "cms.content.read",
            "cms.content.write",
            "cms.content.publish",
            "commerce.product.read",
            "commerce.product.manage",
            "commerce.order.read",
            "commerce.order.manage",
        ),
        "Day-to-day administration of one club.",
    ),
    RoleTemplate(
        "ACADEMY_DIRECTOR",
        "Academy Director",
        ScopeLevel.CLUB,
        (
            *_COACH,
            "clubs.season.manage",
            "teams.team.manage",
            "people.person.manage",
            "players.player.create",
            "players.player.update",
            "players.document.manage",
            "staff.profile.read",
            "authz.role.read",
            "cms.content.read",
        ),
        "The whole academy: teams, players, coaches, training and development.",
    ),
    RoleTemplate(
        "HEAD_COACH",
        "Head Coach",
        ScopeLevel.CLUB,
        (*_COACH, "players.player.update"),
        "Coaching across the club.",
    ),
    RoleTemplate(
        "COACH",
        "Coach",
        ScopeLevel.TEAM,
        _COACH,
        "Coaching one team. Cannot see other teams or any financial data.",
    ),
    RoleTemplate(
        "TEAM_MANAGER",
        "Team Manager",
        ScopeLevel.TEAM,
        (*_READ_ONLY_CLUB, "training.attendance.record"),
        "Logistics and attendance for one team.",
    ),
    RoleTemplate(
        "CONTENT_MANAGER",
        "Content Manager",
        ScopeLevel.CLUB,
        (
            "clubs.club.read",
            "teams.team.read",
            "players.player.read",
            "cms.content.read",
            "cms.content.write",
            "cms.content.publish",
        ),
        "The club website and news. No access to player records beyond names.",
    ),
    RoleTemplate(
        "FINANCE_MANAGER",
        "Finance Manager",
        ScopeLevel.TENANT,
        ("clubs.club.read", "finance.report.read", "billing.subscription.read"),
        "Financial reporting. No access to player or medical data.",
    ),
    RoleTemplate(
        "MEDICAL_STAFF",
        "Physio / Medical",
        ScopeLevel.CLUB,
        (
            *_READ_ONLY_CLUB,
            "medical.record.read",
            "medical.record.write",
            "medical.availability.set",
        ),
        "Clinical records. Requires MFA and recent strong authentication.",
    ),
)

BY_KEY_TEMPLATE = {t.key: t for t in TEMPLATES}


def validate_templates() -> None:
    """Fail fast at import/seed time rather than at a permission check."""
    for template in TEMPLATES:
        is_platform = template.scope_level is ScopeLevel.PLATFORM

        for key in template.permissions:
            permission = BY_KEY.get(key)
            if permission is None:
                raise ValueError(f"{template.key} references unknown permission {key!r}")

            # A permission may always be granted *more narrowly* than declared —
            # that is strictly less privilege. It may never be granted more
            # broadly: `billing.subscription.manage` is TENANT-only and must not
            # end up on a club role.
            #
            # Platform roles are exempt because PLATFORM scope contains every
            # other scope by construction; their guard is the two rules below.
            broadest = min(permission.scope_levels)
            if not is_platform and template.scope_level < broadest:
                raise ValueError(
                    f"{template.key} is a {template.scope_level.name} role but "
                    f"{key!r} may not be granted more broadly than {broadest.name}"
                )

        if not is_platform and any(k.startswith("platform.") for k in template.permissions):
            raise ValueError(f"{template.key} must not carry platform permissions")

        # Special-category data under GDPR Art. 9. Platform staff have no route
        # to a diagnosis, with no override — a support case needing clinical
        # detail is handled by the tenant, not by us.
        # See docs/architecture/06-authorization.md §8.
        if is_platform and any(k.startswith("medical.") for k in template.permissions):
            raise ValueError(
                f"{template.key} is a platform role and must not carry medical permissions"
            )


validate_templates()
