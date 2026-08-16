"""Permission resolution.

Resolved once per request from our own tables — never from the token — so a
revoked role takes effect on the next request rather than at the next token
refresh. Cached in Redis behind a per-user version counter, so an assignment
change invalidates immediately and the TTL is only a safety net.
"""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz.models import Role, RoleAssignment, RolePermission
from app.authz.permissions import EffectivePermissions
from app.authz.scope import Scope, ScopeLevel
from app.core.cache import cache

log = structlog.get_logger(__name__)

# Public because the reference seed clears this prefix after changing a
# role's permissions — see app/platform/seeds/reference.py.
CACHE_PREFIX = "perm"


def _version_key(user_id: UUID) -> str:
    return f"{CACHE_PREFIX}:ver:{user_id}"


def _grants_key(user_id: UUID, tenant_id: UUID | None, version: int) -> str:
    return f"{CACHE_PREFIX}:v{version}:{user_id}:{tenant_id or 'platform'}"


class PermissionResolver:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def resolve(self, user_id: UUID, tenant_id: UUID | None) -> EffectivePermissions:
        version = await cache.get_int(_version_key(user_id), default=1)
        key = _grants_key(user_id, tenant_id, version)

        cached = await cache.get_json(key)
        if cached is not None:
            return _deserialise(cached)

        effective = await self._load(user_id, tenant_id)
        await cache.set_json(key, _serialise(effective), ttl=60)
        return effective

    async def _load(self, user_id: UUID, tenant_id: UUID | None) -> EffectivePermissions:
        now = func.now()
        stmt = (
            select(
                RolePermission.permission_key,
                Role.scope_level,
                RoleAssignment.tenant_id,
                RoleAssignment.club_id,
                RoleAssignment.team_id,
            )
            .join(Role, Role.id == RoleAssignment.role_id)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .where(
                RoleAssignment.user_id == user_id,
                RoleAssignment.revoked_at.is_(None),
                or_(RoleAssignment.valid_from.is_(None), RoleAssignment.valid_from <= now),
                or_(
                    RoleAssignment.valid_until.is_(None),
                    RoleAssignment.valid_until > now,
                ),
                # Platform assignments (tenant_id NULL) always apply; tenant
                # assignments only inside the tenant being requested.
                or_(
                    RoleAssignment.tenant_id.is_(None),
                    RoleAssignment.tenant_id == tenant_id,
                ),
            )
        )

        grants: defaultdict[str, set[Scope]] = defaultdict(set)
        is_platform = False

        for key, level_name, assign_tenant, club_id, team_id in await self.session.execute(
            stmt
        ):
            level = ScopeLevel.parse(level_name)
            if level is ScopeLevel.PLATFORM:
                is_platform = True
                grants[key].add(Scope.platform())
                continue
            if assign_tenant is None:
                continue

            # The effective level is the narrowest of what was declared and what
            # was actually pinned on the assignment.
            if team_id is not None:
                scope = Scope.team(assign_tenant, club_id, team_id)  # type: ignore[arg-type]
            elif club_id is not None:
                scope = Scope.club(assign_tenant, club_id)
            else:
                scope = Scope.tenant(assign_tenant)
            grants[key].add(scope)

        return EffectivePermissions(
            grants={k: frozenset(v) for k, v in grants.items()},
            is_platform=is_platform,
        )

    async def invalidate(self, user_id: UUID) -> None:
        """Called by every write to role, role_permission or role_assignment."""
        await cache.incr(_version_key(user_id))


def _serialise(effective: EffectivePermissions) -> dict[str, object]:
    return {
        "is_platform": effective.is_platform,
        "grants": {
            key: [
                {
                    "level": scope.level.name,
                    "tenant_id": str(scope.tenant_id) if scope.tenant_id else None,
                    "club_id": str(scope.club_id) if scope.club_id else None,
                    "team_id": str(scope.team_id) if scope.team_id else None,
                }
                for scope in scopes
            ]
            for key, scopes in effective.grants.items()
        },
    }


def _deserialise(payload: dict) -> EffectivePermissions:  # type: ignore[type-arg]
    grants: dict[str, frozenset[Scope]] = {}
    for key, scopes in payload.get("grants", {}).items():
        grants[key] = frozenset(
            Scope(
                level=ScopeLevel.parse(s["level"]),
                tenant_id=UUID(s["tenant_id"]) if s["tenant_id"] else None,
                club_id=UUID(s["club_id"]) if s["club_id"] else None,
                team_id=UUID(s["team_id"]) if s["team_id"] else None,
            )
            for s in scopes
        )
    return EffectivePermissions(grants=grants, is_platform=payload.get("is_platform", False))


def scope_filter_for(
    effective: EffectivePermissions, permission: str, tenant_id: UUID
) -> ScopeFilter:
    """Narrow a collection query to what the caller may actually see.

    A permission check answers "may you do this at all"; this answers "to which
    rows". Without it, a team-scoped coach listing players would see the club.
    """
    scopes = effective.scopes_for(permission)
    if any(s.level in (ScopeLevel.PLATFORM, ScopeLevel.TENANT) for s in scopes):
        return ScopeFilter(unrestricted=True)
    return ScopeFilter(
        club_ids=frozenset(s.club_id for s in scopes if s.club_id and not s.team_id),
        team_ids=frozenset(s.team_id for s in scopes if s.team_id),
    )


class ScopeFilter:
    __slots__ = ("club_ids", "team_ids", "unrestricted")

    def __init__(
        self,
        *,
        unrestricted: bool = False,
        club_ids: frozenset[UUID] = frozenset(),
        team_ids: frozenset[UUID] = frozenset(),
    ) -> None:
        self.unrestricted = unrestricted
        self.club_ids = club_ids
        self.team_ids = team_ids

    @property
    def is_empty(self) -> bool:
        return not self.unrestricted and not self.club_ids and not self.team_ids
