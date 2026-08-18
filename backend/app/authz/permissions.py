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
    # Not step-up. Deleting a player destroys a record and is audited, but it
    # takes nothing out of the building and gains nobody any privilege — and
    # `players.player.update`, which is not sensitive, already marks a player
    # DEPARTED and removes them from the club's website. A control that guards
    # one route to an outcome and leaves the other open is not protecting the
    # outcome; it is only making the honest route harder.
    #
    # It stayed sensitive long enough for a club administrator with no second
    # factor to be signed out of the product for trying to tidy up an import.
    _p("players.player.delete", "players", "Remove a player", (T, C)),
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
    # Two permissions, because "add the U15 coach" and "make somebody an
    # administrator" are not the same act. Staffing a club is ordinary work a
    # club secretary does on a Tuesday; delegating the power to grant roles is
    # the classic escalation step, and only that one demands a second factor.
    #
    # Requiring step-up for both was the wrong line: a tenant owner can already
    # delete every player and rewrite the website without one, so a lock on
    # role-granting alone bought no real safety and cost the club the feature.
    _p("authz.role.grant", "authz", "Give somebody a scoped role", (T, C)),
    _p(
        "authz.role.manage",
        "authz",
        "Grant roles that can themselves grant roles",
        (T, C),
        sensitive=True,
    ),
    # --- content ----------------------------------------------------------
    _p("cms.content.read", "cms", "View articles and pages"),
    _p("cms.content.write", "cms", "Write articles and pages"),
    _p("cms.content.publish", "cms", "Publish, schedule and archive content"),
    # --- shop -------------------------------------------------------------
    _p("commerce.product.read", "commerce", "View the shop catalogue"),
    _p("commerce.product.manage", "commerce", "Add and edit shop products"),
    _p("commerce.order.read", "commerce", "View shop orders"),
    _p("commerce.order.manage", "commerce", "Mark orders collected or cancelled"),
    # --- matchday ----------------------------------------------------------
    # Split away from `teams.team.*` so somebody can be given the fixture list
    # and nothing else. A commentator hired for the afternoon should not be
    # able to read the squad, the staff list or a player's documents, and
    # before this the only way to let them see a match was to let them see all
    # of that too.
    _p("matches.match.read", "matches", "View fixtures and results", (T, C, G)),
    # Recording a goal or a card while the match is on. Narrow on purpose: it
    # is the whole job of a matchday commentator, and it is all they get.
    _p("matches.event.record", "matches", "Record live match events", (T, C)),
    # Arranging the team sheet before kick-off. Separate from recording events
    # because the two are done by different people at different times — a press
    # officer sets the eleven at two o'clock and somebody else calls the game.
    _p("matches.lineup.manage", "matches", "Set the starting eleven", (T, C)),
    # --- stadium & ticketing ----------------------------------------------
    # Split along the lines of who actually does the work on a matchday. A
    # ticketing manager draws the ground and sets prices; a box-office clerk
    # sells and reprints but must not be able to reprice a stand; a steward on
    # a turnstile needs one permission and nothing else.
    _p("ticketing.venue.read", "ticketing", "View stadiums and configurations"),
    _p("ticketing.venue.manage", "ticketing", "Draw and edit stadium configurations"),
    # Publishing freezes a layout that matches will be sold from, so it is a
    # separate permission from drawing one — the same split as cms.content.
    _p("ticketing.venue.publish", "ticketing", "Publish a stadium configuration"),
    _p("ticketing.event.read", "ticketing", "View ticketed matches"),
    _p("ticketing.event.manage", "ticketing", "Create and edit ticketed matches"),
    _p("ticketing.pricing.manage", "ticketing", "Set ticket prices and promotional codes"),
    # Holding back seats is how a stand gets closed and how a sponsor gets its
    # block. Both change what the public can buy, so they travel together.
    _p("ticketing.allocation.manage", "ticketing", "Hold and allocate inventory"),
    _p("ticketing.order.read", "ticketing", "View ticket orders and customers"),
    # The box office: sell at the counter, reissue a lost ticket, refund one.
    _p("ticketing.order.manage", "ticketing", "Sell, reissue and refund tickets"),
    _p("ticketing.season.manage", "ticketing", "Create and sell season tickets"),
    # What a steward's handset holds. Deliberately narrow: it admits people and
    # can read nothing else about the club.
    _p("ticketing.access.scan", "ticketing", "Validate tickets at a gate"),
    _p("ticketing.access.manage", "ticketing", "Enrol and revoke scanner devices"),
    _p("ticketing.report.read", "ticketing", "View ticketing reports"),
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
    _p("payments.settings.read", "payments", "View the card gateway settings", (T,)),
    # Sensitive, and tenant-level: these credentials are what takes a
    # supporter's money, and whoever holds them can take it somewhere else.
    _p(
        "payments.settings.manage",
        "payments",
        "Set up the card gateway",
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
