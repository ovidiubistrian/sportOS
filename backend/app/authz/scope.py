"""Authorization scopes.

A scope is a nested triple. Containment is strict: a permission held at CLUB
covers every team in that club; a permission held at TEAM covers only that team.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from uuid import UUID


class ScopeLevel(IntEnum):
    """Ordered from broadest to narrowest, so comparisons read naturally."""

    PLATFORM = 0
    TENANT = 1
    CLUB = 2
    TEAM = 3

    @classmethod
    def parse(cls, value: str) -> ScopeLevel:
        return cls[value.upper()]


@dataclass(frozen=True, slots=True)
class Scope:
    level: ScopeLevel
    tenant_id: UUID | None = None
    club_id: UUID | None = None
    team_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.level >= ScopeLevel.TENANT and self.tenant_id is None:
            raise ValueError("tenant-level scope requires a tenant_id")
        if self.level == ScopeLevel.CLUB and self.club_id is None:
            raise ValueError("club-level scope requires a club_id")
        if self.level == ScopeLevel.TEAM and self.team_id is None:
            raise ValueError("team-level scope requires a team_id")
        # A TEAM scope may omit club_id. Callers routinely identify a team
        # without naming its club (`?team_id=…`), and requiring a lookup just
        # to build the scope would put a query in the authorization path.
        # Containment compares only the dimensions both sides constrain, and
        # the repository's ScopeFilter still restricts the rows returned.

    # --- constructors -----------------------------------------------------

    @classmethod
    def platform(cls) -> Scope:
        return cls(ScopeLevel.PLATFORM)

    @classmethod
    def tenant(cls, tenant_id: UUID) -> Scope:
        return cls(ScopeLevel.TENANT, tenant_id=tenant_id)

    @classmethod
    def club(cls, tenant_id: UUID, club_id: UUID) -> Scope:
        return cls(ScopeLevel.CLUB, tenant_id=tenant_id, club_id=club_id)

    @classmethod
    def team(cls, tenant_id: UUID, club_id: UUID | None, team_id: UUID) -> Scope:
        return cls(ScopeLevel.TEAM, tenant_id=tenant_id, club_id=club_id, team_id=team_id)

    @classmethod
    def narrowest(
        cls,
        tenant_id: UUID,
        club_id: UUID | None = None,
        team_id: UUID | None = None,
    ) -> Scope:
        """Build the scope a request is actually asking about.

        The level follows the most specific identifier supplied, so a route
        never has to declare it twice.
        """
        if team_id is not None:
            return cls.team(tenant_id, club_id, team_id)
        if club_id is not None:
            return cls.club(tenant_id, club_id)
        return cls.tenant(tenant_id)

    # --- containment ------------------------------------------------------

    def contains(self, other: Scope) -> bool:
        """True when a grant at `self` authorises an action requested at `other`.

        Prefix matching: where both scopes constrain the same dimension, the
        values must be equal; where only one does, it does not conflict.

        The consequence worth understanding: a TEAM grant satisfies a CLUB-level
        *request*, because a coach must be able to open their own club and list
        "players" without knowing a team id up front. Two things stop that from
        becoming an escalation:

          * a permission declares the levels at which it may be granted, so a
            team-scoped role cannot hold `clubs.club.update` at all; and
          * collection endpoints narrow their results with `ScopeFilter`, so the
            coach's player list contains only their own teams.

        A TEAM grant never satisfies a request scoped to a *different* team.
        """
        if self.level == ScopeLevel.PLATFORM:
            return True
        if other.level == ScopeLevel.PLATFORM:
            return False
        if self.tenant_id != other.tenant_id:
            return False
        if (
            self.club_id is not None
            and other.club_id is not None
            and self.club_id != other.club_id
        ):
            return False
        return not (
            self.team_id is not None
            and other.team_id is not None
            and self.team_id != other.team_id
        )

    def __str__(self) -> str:
        parts = [self.level.name]
        for label, value in (
            ("t", self.tenant_id),
            ("c", self.club_id),
            ("g", self.team_id),
        ):
            if value is not None:
                parts.append(f"{label}={value}")
        return ":".join(parts)
