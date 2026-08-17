"""Setting up a card gateway, and seeing what it was told.

Three things a club needs and nothing more: somewhere to paste the credentials
the bank issued, a way to find out they work before a supporter does, and the
record of every call made with them.

The password goes in and never comes back out. The screen reports whether one
is set, which is all it needs to render a field, and a club that has lost theirs
gets a new one from the bank rather than from us.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import Db, Requires
from app.audit.service import AuditService
from app.core.context import RequestContext
from app.core.pagination import Page, PageMeta
from app.payments.base import PaymentProviderError
from app.payments.btipay import BtIpayProvider
from app.payments.journal import PaymentJournal
from app.payments.models import PaymentCredential, PaymentProviderCall

router = APIRouter(prefix="/payments", tags=["payments"])

READ = "payments.settings.read"
MANAGE = "payments.settings.manage"

# The only provider so far. A literal rather than free text so a typo is a 422
# and not a club that appears configured and cannot take a penny.
ProviderKey = Literal["btipay"]


class GatewaySettings(BaseModel):
    """What a club sees. Never the password."""

    provider: str
    is_live: bool
    sandbox: bool
    user_name: str
    has_password: bool
    child_id: str | None = None
    updated_at: datetime | None = None


class GatewayIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_name: str = Field(min_length=1, max_length=120)
    # Optional on an update: a club editing the user name should not have to
    # retype a password it cannot read back.
    password: str | None = Field(default=None, min_length=1, max_length=200)
    sandbox: bool = True
    child_id: str | None = Field(default=None, max_length=64)
    # Off by default, and its own decision. Credentials that work are not the
    # same as a club being ready to take money, and the gap between those two
    # is where a club tests.
    is_live: bool = False


def _view(row: PaymentCredential) -> GatewaySettings:
    settings = row.settings or {}
    return GatewaySettings(
        provider=row.provider,
        is_live=row.is_live,
        sandbox=bool(settings.get("sandbox", True)),
        user_name=str(settings.get("user_name") or settings.get("userName") or ""),
        has_password=bool(settings.get("password")),
        child_id=settings.get("child_id") or settings.get("childId"),
        updated_at=row.updated_at,
    )


@router.get("/settings", response_model=list[GatewaySettings], summary="Card gateways")
async def list_settings(
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(READ))],
) -> list[GatewaySettings]:
    rows = await db.scalars(
        select(PaymentCredential).where(PaymentCredential.tenant_id == ctx.tenant)
    )
    return [_view(row) for row in rows]


@router.put(
    "/settings/{provider}",
    response_model=GatewaySettings,
    summary="Set up a card gateway",
)
async def save_settings(
    provider: ProviderKey,
    payload: GatewayIn,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(MANAGE))],
) -> GatewaySettings:
    row = await db.scalar(
        select(PaymentCredential).where(
            PaymentCredential.tenant_id == ctx.tenant,
            PaymentCredential.provider == provider,
        )
    )
    existing = dict(row.settings or {}) if row else {}

    password = payload.password or existing.get("password") or ""
    if not password:
        raise PaymentProviderError("A password is needed before this can be saved.")

    settings = {
        "user_name": payload.user_name.strip(),
        "password": password,
        "sandbox": payload.sandbox,
        "child_id": (payload.child_id or None),
    }

    if row is None:
        row = PaymentCredential(tenant_id=ctx.tenant, provider=provider)
        db.add(row)
    row.settings = settings
    row.is_live = payload.is_live
    row.updated_by = ctx.actor_id

    AuditService(db).record(
        ctx,
        action="payments.settings.update",
        object_type="payment_credential",
        object_id=row.id,
        # The values are not recorded. That one of them changed is the fact
        # worth keeping; what it changed to is a credential.
        after={"provider": provider, "is_live": payload.is_live, "sandbox": payload.sandbox},
    )
    await db.flush()
    return _view(row)


@router.post("/settings/{provider}/test", summary="Check the gateway answers to these")
async def test_settings(
    provider: ProviderKey,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(MANAGE))],
) -> dict[str, Any]:
    """Ask the gateway about an order that cannot exist.

    Its refusal is the answer: "no such order" from somebody allowed to ask
    proves the credentials, and nothing is registered and no money moves. Runs
    against what is saved, live or not — the point is to find out before a
    supporter does.
    """
    row = await db.scalar(
        select(PaymentCredential).where(
            PaymentCredential.tenant_id == ctx.tenant,
            PaymentCredential.provider == provider,
        )
    )
    if row is None:
        return {"ok": False, "error": "Nothing is set up for this gateway yet."}

    settings = row.settings or {}
    try:
        gateway = BtIpayProvider(
            user_name=str(settings.get("user_name") or settings.get("userName") or ""),
            password=str(settings.get("password") or ""),
            sandbox=bool(settings.get("sandbox", True)),
            child_id=settings.get("child_id") or settings.get("childId") or None,
        ).with_journal(PaymentJournal(ctx.tenant, order_ref=None))
        return await gateway.test_connection()
    except PaymentProviderError as exc:
        return {"ok": False, "error": str(exc)}


class GatewayCall(BaseModel):
    id: UUID
    provider: str
    endpoint: str
    order_ref: str | None
    provider_order_id: str | None
    ok: bool
    http_status: int | None
    error_code: str | None
    error_message: str | None
    latency_ms: int | None
    created_at: datetime


class GatewayCallDetail(GatewayCall):
    """What went and what came back, secrets removed. This is what a club
    sends the bank when the two of them disagree about a payment."""

    sent: dict
    received: dict


@router.get("/calls", response_model=Page[GatewayCall], summary="Everything said to a gateway")
async def list_calls(
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(READ))],
    order_ref: Annotated[str | None, Query()] = None,
    failed_only: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[GatewayCall]:
    query = select(PaymentProviderCall).where(PaymentProviderCall.tenant_id == ctx.tenant)
    if order_ref:
        query = query.where(PaymentProviderCall.order_ref == order_ref)
    if failed_only:
        query = query.where(PaymentProviderCall.ok.is_(False))

    rows = list(
        await db.scalars(
            query.order_by(PaymentProviderCall.created_at.desc()).limit(limit).offset(offset)
        )
    )
    return Page(
        data=[GatewayCall.model_validate(row, from_attributes=True) for row in rows],
        page=PageMeta(limit=limit, offset=offset, has_more=len(rows) == limit),
    )


@router.get(
    "/calls/{call_id}",
    response_model=GatewayCallDetail,
    summary="One call, in full",
)
async def get_call(
    call_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(READ))],
) -> GatewayCallDetail:
    from app.core.errors import NotFound

    row = await db.scalar(
        select(PaymentProviderCall).where(
            PaymentProviderCall.tenant_id == ctx.tenant,
            PaymentProviderCall.id == call_id,
        )
    )
    if row is None:
        raise NotFound(object_type="payment_provider_call", object_id=str(call_id))
    return GatewayCallDetail.model_validate(row, from_attributes=True)
