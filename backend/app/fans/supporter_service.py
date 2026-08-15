"""Recognising a supporter on an otherwise public request.

The public site is unauthenticated by design, so nothing here may *require* a
token. What it does is notice one: a supporter who happens to be signed in gets
their purchase attached to their account, and everybody else checks out as a
guest exactly as before.

That is why `optional_subject` swallows a bad token instead of rejecting it. On
a route where identity is a bonus rather than a gate, a supporter whose session
quietly expired between filling the basket and pressing pay must still be able
to pay — refusing the sale to protect an account they were not using is the
wrong trade.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Unauthenticated
from app.fans.supporter_models import Supporter
from app.identity.models import UserAccount
from app.identity.tokens import verify_access_token

bearer = HTTPBearer(auto_error=False)


async def optional_subject(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> str | None:
    """Who is signed in, if anybody. Never raises."""
    if credentials is None:
        return None
    try:
        claims = await verify_access_token(credentials.credentials)
    except Unauthenticated:
        return None
    return claims.subject_id


async def supporter_id_for(
    session: AsyncSession, *, club_id: UUID, subject: str | None
) -> UUID | None:
    """This club's supporter row for that login, if the relationship exists.

    Scoped to the club by the caller's route, never by anything the client
    sent: the same login is a different supporter at every club, and the domain
    is what decides which one this request is about.
    """
    if subject is None:
        return None

    account = await session.scalar(
        select(UserAccount.id).where(UserAccount.subject_id == subject)
    )
    if account is None:
        return None

    return await session.scalar(
        select(Supporter.id).where(Supporter.club_id == club_id, Supporter.user_id == account)
    )
