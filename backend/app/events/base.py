"""Domain event contract.

Payload rules, enforced by review and by `tests/events/test_event_contract.py`:

  * **IDs and immutable facts only.** By the time a handler runs the entity may
    have changed, so a snapshot in the payload is a bug generator.
  * **No PII beyond an identifier.** Events are persisted, retried and logged.
    Keeping them PII-free is what stops GDPR erasure from having to rewrite
    event history. A handler that needs an email fetches it — and re-checks
    consent — at send time.
  * Additive changes only within a version; a breaking change bumps
    `event_version` and both are handled during the transition.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, ClassVar, Self
from uuid import UUID

from app.core.ids import new_id


@dataclass(frozen=True, slots=True)
class DomainEvent:
    aggregate_id: UUID
    payload: dict[str, Any] = field(default_factory=dict)
    tenant_id: UUID | None = None
    id: UUID = field(default_factory=new_id)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    correlation_id: str | None = None
    causation_id: UUID | None = None

    # Set by each concrete subclass.
    event_type: ClassVar[str] = ""
    event_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = ""

    def __post_init__(self) -> None:
        if not self.event_type or not self.aggregate_type:
            raise TypeError(
                f"{type(self).__name__} must define event_type and aggregate_type"
            )

    @classmethod
    def of(cls, aggregate_id: UUID, tenant_id: UUID | None = None, **payload: Any) -> Self:
        return cls(aggregate_id=aggregate_id, tenant_id=tenant_id, payload=payload)


# --- Catalogue ------------------------------------------------------------
# Declared centrally so the set of events is greppable in one place, and so a
# handler cannot subscribe to an event nobody publishes.


@dataclass(frozen=True, slots=True)
class PlayerRegistered(DomainEvent):
    event_type: ClassVar[str] = "players.player_registered"
    aggregate_type: ClassVar[str] = "player"


@dataclass(frozen=True, slots=True)
class PlayerStatusChanged(DomainEvent):
    event_type: ClassVar[str] = "players.player_status_changed"
    aggregate_type: ClassVar[str] = "player"


@dataclass(frozen=True, slots=True)
class PlayerTransferred(DomainEvent):
    event_type: ClassVar[str] = "players.player_transferred"
    aggregate_type: ClassVar[str] = "player"


@dataclass(frozen=True, slots=True)
class RoleAssigned(DomainEvent):
    event_type: ClassVar[str] = "identity.role_assigned"
    aggregate_type: ClassVar[str] = "user_account"


@dataclass(frozen=True, slots=True)
class RoleRevoked(DomainEvent):
    event_type: ClassVar[str] = "identity.role_revoked"
    aggregate_type: ClassVar[str] = "user_account"


@dataclass(frozen=True, slots=True)
class TenantCreated(DomainEvent):
    event_type: ClassVar[str] = "tenants.tenant_created"
    aggregate_type: ClassVar[str] = "tenant"


@dataclass(frozen=True, slots=True)
class ClubBrandingChanged(DomainEvent):
    event_type: ClassVar[str] = "tenants.club_branding_changed"
    aggregate_type: ClassVar[str] = "club"


@dataclass(frozen=True, slots=True)
class MatchScheduleChanged(DomainEvent):
    """A fixture was added, moved, or had its result recorded.

    Carries the club, not the match: the site renders a whole fixture list and a
    whole table, so a single result invalidates both regardless of which match
    produced it.
    """

    event_type: ClassVar[str] = "competitions.match_schedule_changed"
    aggregate_type: ClassVar[str] = "club"


@dataclass(frozen=True, slots=True)
class ContentPublished(DomainEvent):
    event_type: ClassVar[str] = "cms.content_published"
    aggregate_type: ClassVar[str] = "content_item"


@dataclass(frozen=True, slots=True)
class SubscriptionChanged(DomainEvent):
    event_type: ClassVar[str] = "billing.subscription_changed"
    aggregate_type: ClassVar[str] = "tenant_subscription"


EVENT_TYPES: dict[str, type[DomainEvent]] = {
    subclass.event_type: subclass
    for subclass in DomainEvent.__subclasses__()
    if subclass.event_type
}
