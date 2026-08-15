"""The permission catalogue and effective-permission resolution.

Business logic checks permission keys, never role names. That is what makes
tenant-defined custom roles possible without touching code, and what keeps
"who can do this?" answerable by reading one file.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from app.authz.scope import Scope, ScopeLevel

T, C, G = ScopeLevel.TENANT, ScopeLevel.CLUB, ScopeLevel.TEAM
P = ScopeLevel.PLATFORM


@dataclass(frozen=True, slots=True)
class Permission:
    key: str
    module: str
    description: str
    scope_levels: tuple[ScopeLevel, ...]
    # Sensitive permissions force an audit record and recent strong authentication.
    is_sensitive: bool = False


def _p(
    key: str,
    module: str,
    description: str,
    levels: tuple[ScopeLevel, ...] = (T, C),
    *,
    sensitive: bool = False,
) -> Permission:
    return Permission(key, module, description, levels, sensitive)


CATALOGUE: tuple[Permission, ...] = (
    # --- clubs & organisation -------------------------------------------
    _p("clubs.club.read", "clubs", "View club details"),
    _p("clubs.club.update", "clubs", "Edit club details"),
    _p("clubs.season.manage", "clubs", "Create and edit seasons"),
    # --- teams ------------------------------------------------------------
    _p("teams.team.read", "teams", "View teams", (T, C, G)),
    _p("teams.team.manage", "teams", "Create and edit teams"),
    # --- people & players -------------------------------------------------
    _p("people.person.read", "people", "View people"),
    _p("people.person.manage", "people", "Create and edit people"),
    _p("people.person.export", "people", "Export personal data", sensitive=True),
    _p("players.player.read", "players", "View players", (T, C, G)),
    _p("players.player.create", "players", "Register a player", (T, C, G)),
    _p("players.player.update", "players", "Edit a player", (T, C, G)),
    _p("players.player.delete", "players", "Remove a player", (T, C), sensitive=True),
    _p("players.document.read", "players", "View player documents", (T, C, G)),
    _p("players.document.manage", "players", "Upload player documents", (T, C, G)),
    # --- staff ------------------------------------------------------------
    _p("staff.profile.read", "staff", "View staff"),
    _p("staff.profile.manage", "staff", "Create and edit staff"),
    # --- training ---------------------------------------------------------
    _p("training.session.read", "training", "View training sessions", (T, C, G)),
    _p("training.session.manage", "training", "Plan training sessions", (T, C, G)),
    _p("training.attendance.record", "training", "Record attendance", (T, C, G)),
    # --- development ------------------------------------------------------
    _p("development.evaluation.read", "development", "View evaluations", (T, C, G)),
    _p("development.evaluation.manage", "development", "Write evaluations", (T, C, G)),
    # --- medical (structurally separated; see docs 06 §5) -----------------
    _p("medical.record.read", "medical", "View clinical records", (T, C), sensitive=True),
    _p("medical.record.write", "medical", "Write clinical records", (T, C), sensitive=True),
    _p("medical.availability.set", "medical", "Set player availability", (T, C, G)),
    # --- authorization ----------------------------------------------------
    _p("authz.role.read", "authz", "View roles and assignments"),
    _p("authz.role.manage", "authz", "Grant and revoke roles", (T, C), sensitive=True),
    # --- content ----------------------------------------------------------
    _p("cms.content.read", "cms", "View articles and pages"),
    _p("cms.content.write", "cms", "Write articles and pages"),
    _p("cms.content.publish", "cms", "Publish, schedule and archive content"),
    # --- shop -------------------------------------------------------------
    _p("commerce.product.read", "commerce", "View the shop catalogue"),
    _p("commerce.product.manage", "commerce", "Add and edit shop products"),
    _p("commerce.order.read", "commerce", "View shop orders"),
    _p("commerce.order.manage", "commerce", "Mark orders collected or cancelled"),
    # --- finance & billing ------------------------------------------------
    _p("finance.report.read", "finance", "View financial reports"),
    _p("billing.subscription.read", "billing", "View the subscription"),
    _p(
        "billing.subscription.manage",
        "billing",
        "Change the subscription",
        (T,),
        sensitive=True,
    ),
    # --- platform ---------------------------------------------------------
    _p("platform.tenant.read", "platform", "View tenants", (P,)),
    _p("platform.tenant.manage", "platform", "Create and edit tenants", (P,), sensitive=True),
    _p("platform.impersonate", "platform", "Impersonate a tenant user", (P,), sensitive=True),
    # Not sensitive: competitions are public reference data — the Romanian
    # second division is not anybody's private information. Suspending a tenant
    # or moving it between plans is, which is why those stay behind step-up.
    _p("platform.competition.manage", "platform", "Curate the competition catalogue", (P,)),
)

BY_KEY: Mapping[str, Permission] = {p.key: p for p in CATALOGUE}


def get_permission(key: str) -> Permission:
    try:
        return BY_KEY[key]
    except KeyError as exc:
        raise KeyError(
            f"Unknown permission {key!r}. Add it to app/authz/permissions.py "
            "so it is seeded and covered by the permission matrix test."
        ) from exc


@dataclass(frozen=True, slots=True)
class EffectivePermissions:
    """What a user may do in one tenant, resolved once per request."""

    grants: Mapping[str, frozenset[Scope]] = field(default_factory=dict)
    is_platform: bool = False

    def allows(self, permission: str, scope: Scope) -> bool:
        held = self.grants.get(permission)
        if not held:
            return False
        return any(granted.contains(scope) for granted in held)

    def scopes_for(self, permission: str) -> frozenset[Scope]:
        return self.grants.get(permission, frozenset())

    def any_of(self, permissions: tuple[str, ...], scope: Scope) -> bool:
        return any(self.allows(p, scope) for p in permissions)

    @property
    def keys(self) -> frozenset[str]:
        return frozenset(self.grants)
