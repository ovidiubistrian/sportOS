"""Super-admin control over the writing assistant.

The API key is not here, and cannot be set here. One platform-held key serves
every tenant, and it is read from the environment (a secret manager in
production) — a provider secret stored in the application database is one dump,
backup or CSV export away from disclosure, and no admin screen is worth that.

What the super admin controls is the *policy* around the key: which tenants may
use the assistant, and how much of it each may use. That is the decision that
actually needs a human, because the platform pays the bill.

Lives in `platform`, not `ai`, because it reads across every tenant and writes
billing entitlements — tier 5 work. `app/ai` stays a tier-3 module that knows
only about one tenant at a time.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.ai.models import AiUsage
from app.ai.provider import get_provider
from app.api.deps import Requires
from app.audit.service import AuditService
from app.authz.scope import ScopeLevel
from app.billing.features import Feature
from app.billing.models import Entitlement
from app.billing.service import EntitlementService, invalidate_entitlements
from app.core.config import settings
from app.core.context import RequestContext
from app.core.db import platform_session
from app.core.errors import NotFound
from app.tenants.models import Tenant

router = APIRouter(prefix="/platform/ai", tags=["platform"])

MANAGE = Requires("platform.tenant.manage", scope_level=ScopeLevel.PLATFORM)
READ = Requires("platform.tenant.read", scope_level=ScopeLevel.PLATFORM)


class TenantUsage(BaseModel):
    tenant_id: UUID
    tenant_name: str
    enabled: bool
    monthly_limit: int | None
    requests_this_month: int
    input_tokens: int
    output_tokens: int
    accepted: int
    rejected: int


class PlatformAiStatus(BaseModel):
    # Whether a key is present — never the key, never a prefix of it.
    key_configured: bool
    model: str
    period_start: datetime
    total_requests: int
    total_input_tokens: int
    total_output_tokens: int
    tenants: list[TenantUsage]


class TenantPolicyOut(BaseModel):
    tenant_id: UUID
    tenant_name: str
    enabled: bool
    monthly_limit: int | None
    requests_this_month: int


class TenantPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    # None means unlimited, which on a key the platform pays for should be a
    # deliberate act — hence the explicit null rather than an omitted field.
    monthly_limit: int | None = Field(default=None, ge=0, le=1_000_000)
    reason: str = Field(min_length=3, max_length=500)


def _period_start() -> datetime:
    return datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


@router.get("", response_model=PlatformAiStatus, summary="Assistant usage across tenants")
async def status(ctx: Annotated[RequestContext, Depends(READ)]) -> PlatformAiStatus:
    start = _period_start()

    async with platform_session(reason="review ai usage across tenants") as session:
        rows = (
            await session.execute(
                select(
                    Tenant.id,
                    func.coalesce(Tenant.trading_name, Tenant.legal_name),
                    func.count(AiUsage.id),
                    func.coalesce(func.sum(AiUsage.input_tokens), 0),
                    func.coalesce(func.sum(AiUsage.output_tokens), 0),
                    func.count(AiUsage.id).filter(AiUsage.accepted.is_(True)),
                    func.count(AiUsage.id).filter(AiUsage.accepted.is_(False)),
                )
                .select_from(Tenant)
                .join(
                    AiUsage,
                    (AiUsage.tenant_id == Tenant.id) & (AiUsage.created_at >= start),
                    isouter=True,
                )
                .group_by(Tenant.id, Tenant.trading_name, Tenant.legal_name)
                .order_by(func.count(AiUsage.id).desc(), Tenant.legal_name)
            )
        ).all()

        tenants: list[TenantUsage] = []
        for tenant_id, name, requests, tokens_in, tokens_out, accepted, rejected in rows:
            entitlements = await EntitlementService(session).resolve(tenant_id)
            tenants.append(
                TenantUsage(
                    tenant_id=tenant_id,
                    tenant_name=name,
                    enabled=entitlements.enabled(Feature.AI_ASSIST),
                    monthly_limit=entitlements.limit(Feature.AI_REQUESTS_PER_MONTH),
                    requests_this_month=requests,
                    input_tokens=tokens_in,
                    output_tokens=tokens_out,
                    accepted=accepted,
                    rejected=rejected,
                )
            )

    return PlatformAiStatus(
        key_configured=get_provider().is_configured,
        model=settings.ai_model,
        period_start=start,
        total_requests=sum(t.requests_this_month for t in tenants),
        total_input_tokens=sum(t.input_tokens for t in tenants),
        total_output_tokens=sum(t.output_tokens for t in tenants),
        tenants=tenants,
    )


@router.put(
    "/tenants/{tenant_id}",
    response_model=TenantPolicyOut,
    summary="Turn the assistant on or off for one tenant",
)
async def set_policy(
    tenant_id: UUID,
    payload: TenantPolicy,
    ctx: Annotated[RequestContext, Depends(MANAGE)],
) -> TenantPolicyOut:
    """Write the override, and say why.

    Stored as an entitlement override rather than a column on the tenant, so it
    goes through exactly the same resolution, caching and audit path as every
    other feature decision. A second mechanism for "is this on?" is a second
    thing that can disagree.
    """
    async with platform_session(reason="set tenant ai policy") as session:
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            raise NotFound(object_type="tenant", object_id=str(tenant_id))

        before = await EntitlementService(session).resolve(tenant_id)
        now = datetime.now(UTC)

        audit = AuditService(session)
        for feature, limit_value in (
            (Feature.AI_ASSIST, None),
            (Feature.AI_REQUESTS_PER_MONTH, payload.monthly_limit),
        ):
            existing = await session.scalar(
                select(Entitlement).where(
                    Entitlement.tenant_id == tenant_id,
                    Entitlement.feature_key == feature.value,
                    Entitlement.effective_to.is_(None),
                )
            )
            if existing is None:
                existing = Entitlement(
                    tenant_id=tenant_id, feature_key=feature.value, source="OVERRIDE"
                )
                session.add(existing)
                await session.flush()

            was = {
                "feature_key": feature.value,
                "enabled": before.enabled(feature),
                "limit_value": before.limit(feature),
            }
            existing.enabled = payload.enabled
            existing.limit_value = limit_value
            existing.effective_from = now
            existing.granted_by = ctx.actor_id
            existing.reason = payload.reason

            # Recorded as an entitlement change, because that is what it is:
            # the same object type, allow-list and history as every other
            # feature decision, rather than a parallel record only this screen
            # writes and only this screen reads.
            audit.record(
                ctx,
                action="billing.entitlement.override",
                object_type="entitlement",
                object_id=existing.id,
                before=was,
                after={
                    "feature_key": feature.value,
                    "enabled": payload.enabled,
                    "limit_value": limit_value,
                    "reason": payload.reason,
                },
            )
        await session.flush()

        start = _period_start()
        used = int(
            await session.scalar(
                select(func.count())
                .select_from(AiUsage)
                .where(AiUsage.tenant_id == tenant_id, AiUsage.created_at >= start)
            )
            or 0
        )
        name = tenant.trading_name or tenant.legal_name

    # After the transaction commits, or a reader could cache the old answer
    # and the tenant would wait out the cache TTL before the change took effect.
    await invalidate_entitlements(tenant_id)

    return TenantPolicyOut(
        tenant_id=tenant_id,
        tenant_name=name,
        enabled=payload.enabled,
        monthly_limit=payload.monthly_limit,
        requests_this_month=used,
    )
