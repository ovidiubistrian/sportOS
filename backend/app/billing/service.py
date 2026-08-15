"""Entitlement resolution.

    plan_version -> plan_feature        the packaged baseline
          overlaid by
    entitlement (OVERRIDE | TRIAL | PROMO, time-bounded)
          =
    what this tenant may do right now

Resolved once per request in a single query and cached in Redis behind a
per-tenant version counter, so a plan change takes effect immediately and the
TTL is only a safety net.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.features import CATALOGUE, Feature, get_feature
from app.billing.models import Entitlement, PlanFeature, TenantSubscription
from app.core.cache import cache
from app.core.config import settings
from app.core.errors import FeatureNotEnabled, LimitExceeded

log = structlog.get_logger(__name__)

_CACHE_PREFIX = "ent"

LIVE_SUBSCRIPTION_STATUSES = ("TRIALING", "ACTIVE", "PAST_DUE")


def _version_key(tenant_id: UUID) -> str:
    return f"{_CACHE_PREFIX}:ver:{tenant_id}"


def _map_key(tenant_id: UUID, version: int) -> str:
    return f"{_CACHE_PREFIX}:v{version}:{tenant_id}"


@dataclass(frozen=True, slots=True)
class FeatureState:
    enabled: bool
    limit: int | None  # None means unlimited


@dataclass(frozen=True, slots=True)
class Entitlements:
    """The resolved feature map for one tenant."""

    features: dict[str, FeatureState]

    def state(self, feature: Feature | str) -> FeatureState:
        spec = get_feature(feature)
        return self.features.get(
            spec.key.value,
            FeatureState(spec.default_enabled, spec.default_limit),
        )

    def enabled(self, feature: Feature | str) -> bool:
        return self.state(feature).enabled

    def limit(self, feature: Feature | str) -> int | None:
        return self.state(feature).limit

    def require(self, feature: Feature | str) -> None:
        spec = get_feature(feature)
        if not self.enabled(spec.key):
            raise FeatureNotEnabled(
                f"{spec.name} is not included in your plan.",
                feature=spec.key.value,
            )

    def check_limit(self, feature: Feature | str, current: int, adding: int = 1) -> None:
        """Assert that `adding` more of something stays within the plan.

        Callers pass a count taken inside the same transaction as the insert,
        so two concurrent creates cannot both see `n-1`.
        """
        spec = get_feature(feature)
        ceiling = self.limit(spec.key)
        if ceiling is None:
            return
        if current + adding > ceiling:
            raise LimitExceeded(
                f"Your plan allows {ceiling} {spec.name.lower()}.",
                feature=spec.key.value,
                limit=ceiling,
                current=current,
            )

    def as_dict(self) -> dict[str, dict[str, object]]:
        return {
            key: {"enabled": state.enabled, "limit": state.limit}
            for key, state in self.features.items()
        }


class EntitlementService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def resolve(self, tenant_id: UUID) -> Entitlements:
        # Default 0, not 1. `invalidate` uses INCR, and INCR on a missing key
        # sets it to 1 — so a default of 1 made the very first invalidation for
        # any tenant a no-op, and the stale map survived until its TTL. The
        # symptom is the worst kind: a plan change that appears to work, and
        # silently does not, for five minutes.
        version = await cache.get_int(_version_key(tenant_id), default=0)
        key = _map_key(tenant_id, version)

        cached = await cache.get_json(key)
        if cached is not None:
            return Entitlements(
                features={
                    name: FeatureState(bool(v["enabled"]), v["limit"])
                    for name, v in cached.items()
                }
            )

        resolved = await self._load(tenant_id)
        await cache.set_json(key, resolved.as_dict(), ttl=settings.entitlement_cache_seconds)
        return resolved

    async def _load(self, tenant_id: UUID) -> Entitlements:
        # Start from the catalogue defaults so a feature added in code behaves
        # predictably before anyone touches a plan.
        features: dict[str, FeatureState] = {
            spec.key.value: FeatureState(spec.default_enabled, spec.default_limit)
            for spec in CATALOGUE
        }

        subscription = await self.session.scalar(
            select(TenantSubscription).where(
                TenantSubscription.tenant_id == tenant_id,
                TenantSubscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
            )
        )

        if subscription is not None:
            rows = await self.session.execute(
                select(
                    PlanFeature.feature_key, PlanFeature.enabled, PlanFeature.limit_value
                ).where(PlanFeature.plan_version_id == subscription.plan_version_id)
            )
            for feature_key, enabled, limit_value in rows:
                features[feature_key] = FeatureState(enabled, limit_value)

        now = datetime.now(UTC)
        overrides = await self.session.execute(
            select(Entitlement.feature_key, Entitlement.enabled, Entitlement.limit_value)
            .where(
                Entitlement.tenant_id == tenant_id,
                or_(Entitlement.effective_from.is_(None), Entitlement.effective_from <= now),
                or_(Entitlement.effective_to.is_(None), Entitlement.effective_to > now),
            )
            .order_by(Entitlement.created_at)
        )
        for feature_key, enabled, limit_value in overrides:
            features[feature_key] = FeatureState(enabled, limit_value)

        return Entitlements(features=features)

    async def invalidate(self, tenant_id: UUID) -> None:
        """Called by every write to a subscription, plan feature or override."""
        await invalidate_entitlements(tenant_id)


async def invalidate_entitlements(tenant_id: UUID) -> None:
    """Bump the tenant's cache version.

    Free-standing because invalidation belongs *after* the writing transaction
    commits, and by then the session that made the change is gone. Requiring one
    to call this would invite invalidating too early, which caches the old
    answer for the next five minutes.
    """
    await cache.incr(_version_key(tenant_id))


def unlimited_entitlements() -> Entitlements:
    """Everything on. For platform-scoped operations and tests only."""
    return Entitlements(
        features={
            # Enabled, and unlimited where a limit applies.
            spec.key.value: FeatureState(True, None)
            for spec in CATALOGUE
        }
    )
