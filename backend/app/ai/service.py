"""The writing assistant.

Every call is metered before it is made and recorded after it returns, because
the platform pays for all tenants on one key. Suggestions are never applied
automatically — the service returns a proposal, and the editor decides.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AiUsage
from app.ai.prompts import (
    BLOCK_SCHEMA,
    HEADLINE_SCHEMA,
    headline_system_prompt,
    polish_system_prompt,
    render_draft,
)
from app.ai.provider import AiRequest, AiResult, get_provider
from app.audit.service import AuditService
from app.billing.features import Feature
from app.cms.article_types import get_type
from app.cms.blocks import validate_body
from app.core.context import RequestContext
from app.core.db import platform_session
from app.core.errors import LimitExceeded, ValidationFailed

log = structlog.get_logger(__name__)

MAX_BLOCKS_PER_REQUEST = 60
MAX_CHARS_PER_REQUEST = 20_000


class WritingAssistant:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- metering ---------------------------------------------------------

    async def usage_this_period(self, tenant_id: UUID) -> int:
        """Calls made in the current calendar month."""
        start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(AiUsage)
                .where(AiUsage.tenant_id == tenant_id, AiUsage.created_at >= start)
            )
            or 0
        )

    async def _check_quota(self, ctx: RequestContext) -> int:
        entitlements = ctx.entitlements
        if entitlements is None:
            raise LimitExceeded("The writing assistant is not available.")

        entitlements.require(Feature.AI_ASSIST)

        used = await self.usage_this_period(ctx.tenant)
        limit = entitlements.limit(Feature.AI_REQUESTS_PER_MONTH)
        if limit is not None and used >= limit:
            raise LimitExceeded(
                f"You have used all {limit} assistant requests for this month.",
                feature=Feature.AI_REQUESTS_PER_MONTH.value,
                limit=limit,
                current=used,
            )
        return used

    async def _record(
        self,
        ctx: RequestContext,
        *,
        operation: str,
        result: AiResult,
        duration_ms: int,
        object_id: UUID | None,
        club_id: UUID | None,
    ) -> UUID:
        """Write the usage row.

        In its own transaction, through the platform role: the tenant's request
        may still fail after this point, but the tokens were spent and the
        platform was billed for them either way.
        """
        async with platform_session(reason="record ai usage", routine=True) as session:
            usage = AiUsage(
                tenant_id=ctx.tenant,
                club_id=club_id,
                actor_user_id=ctx.actor_id,
                operation=operation,
                object_id=object_id,
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                duration_ms=duration_ms,
            )
            session.add(usage)
            await session.flush()
            return usage.id

    # --- operations -------------------------------------------------------

    @staticmethod
    def _validate_draft(title: str, blocks: list[dict]) -> None:
        if not blocks:
            raise ValidationFailed("There is nothing to improve yet — write a draft first.")
        if len(blocks) > MAX_BLOCKS_PER_REQUEST:
            raise ValidationFailed(
                "That article is too long to improve in one go. Try a section at a time.",
                blocks=len(blocks),
                maximum=MAX_BLOCKS_PER_REQUEST,
            )
        size = len(title) + sum(len(str(b.get("text", ""))) for b in blocks)
        if size > MAX_CHARS_PER_REQUEST:
            raise ValidationFailed(
                "That article is too long to improve in one go. Try a section at a time."
            )

    async def polish(
        self,
        ctx: RequestContext,
        *,
        title: str,
        blocks: list[dict],
        locale: str,
        article_type: str,
        object_id: UUID | None = None,
        club_id: UUID | None = None,
    ) -> dict:
        """Propose an improved version of the body.

        Returns a suggestion. Nothing is written to the article — the editor
        reviews a side-by-side diff and chooses.
        """
        self._validate_draft(title, blocks)
        used = await self._check_quota(ctx)

        spec = get_type(article_type)
        started = time.perf_counter()
        result = await get_provider().complete(
            AiRequest(
                system=polish_system_prompt(spec, locale),
                user=render_draft(title, blocks),
                schema=BLOCK_SCHEMA,
                max_tokens=8192,
            )
        )
        duration_ms = int((time.perf_counter() - started) * 1000)

        # Re-validate against our own block models. The output schema already
        # constrains the shape; this rejects anything that satisfies the schema
        # but not our domain rules (block count, field lengths, block types we
        # do not render).
        suggested = validate_body(result.output.get("blocks", []))
        if not suggested:
            raise ValidationFailed("The assistant returned an empty article.")

        usage_id = await self._record(
            ctx,
            operation="POLISH",
            result=result,
            duration_ms=duration_ms,
            object_id=object_id,
            club_id=club_id,
        )

        AuditService(self.session).record(
            ctx,
            action="cms.content.ai_assist",
            object_type="content_item",
            object_id=object_id,
            club_id=club_id,
            context={"operation": "POLISH", "usage_id": str(usage_id)},
        )

        log.info(
            "ai_polish",
            tenant_id=str(ctx.tenant),
            tokens=result.total_tokens,
            duration_ms=duration_ms,
        )

        return {
            "usage_id": usage_id,
            "blocks": suggested,
            "summary_of_changes": str(result.output.get("summary_of_changes", "")).strip(),
            "requests_used": used + 1,
            "duration_ms": duration_ms,
        }

    async def headlines(
        self,
        ctx: RequestContext,
        *,
        title: str,
        blocks: list[dict],
        locale: str,
        article_type: str,
        object_id: UUID | None = None,
        club_id: UUID | None = None,
    ) -> dict:
        self._validate_draft(title, blocks)
        used = await self._check_quota(ctx)

        spec = get_type(article_type)
        started = time.perf_counter()
        result = await get_provider().complete(
            AiRequest(
                system=headline_system_prompt(spec, locale),
                user=render_draft(title, blocks),
                schema=HEADLINE_SCHEMA,
                max_tokens=1024,
            )
        )
        duration_ms = int((time.perf_counter() - started) * 1000)

        raw = result.output.get("headlines", [])
        suggestions = [str(item).strip() for item in raw if str(item).strip()][:5]
        if not suggestions:
            raise ValidationFailed("The assistant did not return any headlines.")

        usage_id = await self._record(
            ctx,
            operation="HEADLINES",
            result=result,
            duration_ms=duration_ms,
            object_id=object_id,
            club_id=club_id,
        )

        return {
            "usage_id": usage_id,
            "headlines": suggestions,
            "requests_used": used + 1,
            "duration_ms": duration_ms,
        }

    async def mark_outcome(self, usage_id: UUID, *, accepted: bool) -> None:
        """Record whether the editor kept the suggestion.

        The only honest measure of whether this feature earns what it costs.
        """
        async with platform_session(reason="record ai outcome", routine=True) as session:
            usage = await session.get(AiUsage, usage_id)
            if usage is not None:
                usage.accepted = accepted
