"""Audit writing.

Two entry points, for two genuinely different needs:

  * `AuditService.record(...)` — a business event, written **in the caller's
    transaction**. If the change rolls back, so does its audit record; there is
    never an entry for something that did not happen.

  * `record_access(...)` — a sensitive read or an authorization decision,
    written in its own short transaction. Access logging must not be able to
    roll back the user's request, and it is not part of any state change.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.audit.redaction import diff, redact
from app.core.context import RequestContext, current_request_id

log = structlog.get_logger(__name__)


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def record(
        self,
        ctx: RequestContext,
        *,
        action: str,
        object_type: str,
        object_id: UUID | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        club_id: UUID | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Queue an audit row in the caller's transaction."""
        clean_before, clean_after = diff(object_type, before, after)
        principal = ctx.principal

        self.session.add(
            AuditLog(
                tenant_id=ctx.tenant_id,
                club_id=club_id,
                actor_user_id=principal.user_id if principal else None,
                actor_kind="PLATFORM"
                if principal and principal.is_platform_user
                else "USER"
                if principal
                else "SYSTEM",
                impersonated_by_user_id=principal.impersonated_by if principal else None,
                action=action,
                object_type=object_type,
                object_id=object_id,
                before=clean_before,
                after=clean_after,
                request_id=ctx.request_id or current_request_id(),
                context=redact("__context__", context) if context else context,
            )
        )


async def record_access(
    ctx: RequestContext,
    *,
    action: str,
    object_type: str,
    object_id: UUID | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    """Record a sensitive access in its own transaction.

    Deliberately independent of the request's unit of work: a failure to write
    an access log must not fail the request, and a failed request must still
    leave evidence that the access was attempted.
    """
    from app.core.db import tenant_session

    principal = ctx.principal
    try:
        async with tenant_session(ctx.tenant_id) as session:
            session.add(
                AuditLog(
                    tenant_id=ctx.tenant_id,
                    actor_user_id=principal.user_id if principal else None,
                    actor_kind="PLATFORM"
                    if principal and principal.is_platform_user
                    else "USER",
                    impersonated_by_user_id=principal.impersonated_by if principal else None,
                    action=action,
                    object_type=object_type,
                    object_id=object_id,
                    request_id=ctx.request_id or current_request_id(),
                    context=context,
                )
            )
    except Exception:
        # Never let audit writing break the request it is observing. The failure
        # is loud in logs and alerting, not in the user's face.
        log.exception("audit_access_write_failed", action=action)
