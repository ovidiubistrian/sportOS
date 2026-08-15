"""The supporter's own account.

Authenticated, but by a different audience from every other route in this
application: a supporter signs in through the `supporter-web` client and holds
no role in the tenant at all. So these routes cannot use `Requires(...)` — that
resolves a staff permission — and instead identify the caller from their token
and scope everything to the club whose domain they arrived on.

That last part is the whole security model here. A supporter is *not* trusted
to name a club: the host decides which club's data this is, and the account row
is looked up by (that club, this user). A token from one club's site therefore
reads nothing of another's, even though it is the same login.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.core.db import tenant_session
from app.core.errors import NotFound, Unauthenticated
from app.fans.supporter_models import Supporter
from app.fans.supporter_service import bearer
from app.identity.models import UserAccount
from app.identity.tokens import verify_access_token
from app.ordering.models import Order, OrderLine
from app.tenants.models import Club
from app.tenants.site_service import SiteRoute, resolve_host

router = APIRouter(prefix="/public/account", tags=["public"])


class SupporterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    display_name: str
    email: str | None
    phone: str | None
    marketing_opt_in: bool = False


class SupporterUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=2, max_length=160)
    phone: str | None = Field(default=None, max_length=32)
    marketing_opt_in: bool | None = None


class OrderLineOut(BaseModel):
    description: str
    quantity: int
    total_minor: int


class OrderOut(BaseModel):
    reference: str
    status: str
    currency: str
    total_minor: int
    placed_at: datetime | None
    collected_at: datetime | None
    lines: list[OrderLineOut]


def _host(forwarded: str | None, header_host: str | None) -> str | None:
    return (forwarded or header_host or "").split(",")[0].strip() or None


async def _route(forwarded: str | None, header_host: str | None) -> SiteRoute:
    route = await resolve_host(_host(forwarded, header_host))
    if route is None:
        raise NotFound("No club is published on this domain.")
    return route


async def _current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> str:
    """The subject in the token, and nothing more.

    Deliberately not `get_principal`: that resolves staff roles and tenant
    memberships, which a supporter has none of. All that is needed here is
    "who is this", and the club comes from the domain.
    """
    if credentials is None:
        raise Unauthenticated("Sign in to see your account.")
    claims = await verify_access_token(credentials.credentials)
    return claims.subject_id


async def _supporter(session, route: SiteRoute, subject: str) -> Supporter:
    account = await session.scalar(select(UserAccount).where(UserAccount.subject_id == subject))
    if account is None:
        raise NotFound("No account here yet.")

    row = await session.scalar(
        select(Supporter).where(
            Supporter.club_id == route.club_id, Supporter.user_id == account.id
        )
    )
    if row is None:
        raise NotFound("No account here yet.")
    return row


@router.get("", response_model=SupporterOut, summary="Who am I at this club")
async def me(
    response: Response,
    subject: Annotated[str, Depends(_current_user)],
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    host: Annotated[str | None, Header(alias="Host")] = None,
) -> SupporterOut:
    """Creates the club relationship on first visit.

    Signing in on a club's site is what makes somebody a supporter of it, so
    the row is written here rather than demanding a separate "join" step that
    every club would then have to explain.
    """
    route = await _route(x_forwarded_host, host)
    response.headers["Cache-Control"] = "no-store"

    async with tenant_session(route.tenant_id) as session:
        account = await session.scalar(
            select(UserAccount).where(UserAccount.subject_id == subject)
        )
        if account is None:
            raise Unauthenticated("Sign in to see your account.")

        row = await session.scalar(
            select(Supporter).where(
                Supporter.club_id == route.club_id, Supporter.user_id == account.id
            )
        )
        if row is None:
            club = await session.get(Club, route.club_id)
            row = Supporter(
                tenant_id=route.tenant_id,
                club_id=route.club_id,
                user_id=account.id,
                display_name=account.email.split("@")[0] if account.email else "Supporter",
                email=account.email,
                locale=club.default_locale if club else None,
            )
            session.add(row)
            await session.flush()

        row.last_seen_at = datetime.now(UTC)
        return SupporterOut(
            display_name=row.display_name,
            email=row.email,
            phone=row.phone,
            marketing_opt_in=row.marketing_opt_in_at is not None,
        )


@router.put("", response_model=SupporterOut, summary="Update my details")
async def update_me(
    payload: SupporterUpdate,
    response: Response,
    subject: Annotated[str, Depends(_current_user)],
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    host: Annotated[str | None, Header(alias="Host")] = None,
) -> SupporterOut:
    route = await _route(x_forwarded_host, host)
    response.headers["Cache-Control"] = "no-store"

    async with tenant_session(route.tenant_id) as session:
        row = await _supporter(session, route, subject)
        changes = payload.model_dump(exclude_unset=True)

        if "marketing_opt_in" in changes:
            # A timestamp, not a flag: consent has a date, and "when did they
            # agree?" has to be answerable years later.
            row.marketing_opt_in_at = (
                datetime.now(UTC) if changes.pop("marketing_opt_in") else None
            )
        for field, value in changes.items():
            setattr(row, field, value)

        return SupporterOut(
            display_name=row.display_name,
            email=row.email,
            phone=row.phone,
            marketing_opt_in=row.marketing_opt_in_at is not None,
        )


@router.get("/orders", response_model=list[OrderOut], summary="What I have bought")
async def my_orders(
    response: Response,
    subject: Annotated[str, Depends(_current_user)],
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    host: Annotated[str | None, Header(alias="Host")] = None,
) -> list[OrderOut]:
    """This club's orders, for this supporter.

    Matched on the supporter row *and* the club, never on the email address: an
    address is not proof of identity, and matching on one would hand somebody
    else's purchase history to anybody who could guess their email.
    """
    route = await _route(x_forwarded_host, host)
    response.headers["Cache-Control"] = "no-store"

    async with tenant_session(route.tenant_id) as session:
        row = await _supporter(session, route, subject)

        orders = list(
            await session.scalars(
                select(Order)
                .where(Order.club_id == route.club_id, Order.supporter_id == row.id)
                .order_by(Order.placed_at.desc())
                .limit(50)
            )
        )
        if not orders:
            return []

        lines: dict[UUID, list[OrderLine]] = {order.id: [] for order in orders}
        for line in await session.scalars(
            select(OrderLine).where(OrderLine.order_id.in_(lines))
        ):
            lines[line.order_id].append(line)

        return [
            OrderOut(
                reference=order.reference,
                status=order.status,
                currency=order.currency,
                total_minor=order.total_minor,
                placed_at=order.placed_at,
                collected_at=order.collected_at,
                lines=[
                    OrderLineOut(
                        description=line.description,
                        quantity=line.quantity,
                        total_minor=line.total_minor,
                    )
                    for line in lines[order.id]
                ],
            )
            for order in orders
        ]


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, summary="Close my account here")
async def close_account(
    subject: Annotated[str, Depends(_current_user)],
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    host: Annotated[str | None, Header(alias="Host")] = None,
) -> None:
    """Leave one club without losing the login.

    The orders stay — they are the club's financial records, not the
    supporter's to delete — but they stop being linked to a person, which is
    what erasure means here.
    """
    route = await _route(x_forwarded_host, host)

    async with tenant_session(route.tenant_id) as session:
        row = await _supporter(session, route, subject)
        for order in await session.scalars(select(Order).where(Order.supporter_id == row.id)):
            order.supporter_id = None
        await session.delete(row)
