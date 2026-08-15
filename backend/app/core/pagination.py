"""Pagination primitives.

Offset paging for admin tables that need page numbers; cursor paging for feeds
and exports. Offset is capped and its total count is estimated above a
threshold, because an exact `COUNT(*)` on a large tenant table on every page
load is the classic way an admin list gets slow at exactly the volume where it
matters. See docs/architecture/12-api-conventions.md §3.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Query
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationFailed

MAX_LIMIT = 100
MAX_OFFSET = 10_000
EXACT_COUNT_THRESHOLD = 10_000


@dataclass(frozen=True, slots=True)
class PageRequest:
    limit: int = 25
    offset: int = 0
    cursor: str | None = None
    with_total: bool = False

    def __post_init__(self) -> None:
        if self.offset > MAX_OFFSET:
            raise ValidationFailed(
                "Deep offset paging is not supported; use a cursor instead.",
                max_offset=MAX_OFFSET,
            )


def page_params(
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    cursor: Annotated[str | None, Query()] = None,
    with_total: Annotated[bool, Query()] = False,
) -> PageRequest:
    return PageRequest(limit=limit, offset=offset, cursor=cursor, with_total=with_total)


class PageMeta(BaseModel):
    limit: int
    offset: int | None = None
    total: int | None = None
    total_is_estimate: bool = False
    next_cursor: str | None = None
    has_more: bool = False


class Page[T](BaseModel):
    data: list[T]
    page: PageMeta = Field(default_factory=lambda: PageMeta(limit=25))


def encode_cursor(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), default=str).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> dict[str, Any]:
    padding = "=" * (-len(cursor) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(cursor + padding))
    except Exception as exc:
        raise ValidationFailed("Malformed pagination cursor.") from exc


async def count_for(
    session: AsyncSession,
    statement: Select[Any],
    *,
    exact_threshold: int = EXACT_COUNT_THRESHOLD,
) -> tuple[int, bool]:
    """Count rows, capping the work above a threshold.

    Returns `(count, is_estimate)`. The query counts at most
    `exact_threshold + 1` rows, so its cost is bounded regardless of table size.
    Beyond the threshold the count is reported as the threshold with
    `is_estimate=True`, and the UI renders "10,000+" — which is all a human can
    use anyway, and avoids a sequential scan on every page load.
    """
    subquery = statement.limit(exact_threshold + 1).subquery()
    bounded = int(await session.scalar(select(func.count()).select_from(subquery)) or 0)
    if bounded <= exact_threshold:
        return bounded, False
    return exact_threshold, True
