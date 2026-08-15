"""Setting a tenant's languages.

Two settings, two different rules, and the difference is what this service
exists to enforce:

  `default_locale`      the interface language, and the fallback a reader gets
                        when an article has not been translated yet.
  `supported_locales`   the languages the club publishes in.

The default must always be one of the supported ones. Otherwise a club's own
fallback points at a language it does not publish, and every untranslated
article resolves to nothing.

Removing a language is the interesting case: translations already written in it
do not disappear, they stop being served. That is deliberate — deleting a
club's words because someone changed a setting is not a trade anyone agreed to,
and adding the language back restores them.
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import AuditService
from app.core.context import RequestContext
from app.core.errors import ValidationFailed
from app.core.locales import normalise, validate
from app.tenants.models import Tenant

log = structlog.get_logger(__name__)


async def set_languages(
    session: AsyncSession,
    ctx: RequestContext,
    tenant: Tenant,
    *,
    default_locale: str,
    supported_locales: list[str],
) -> Tenant:
    supported = validate(supported_locales)
    default = normalise(default_locale)

    if default not in supported:
        raise ValidationFailed(
            "The default language has to be one the club publishes in.",
            field="default_locale",
            default_locale=default,
            supported=supported,
        )

    before = {
        "default_locale": tenant.default_locale,
        "supported_locales": list(tenant.supported_locales or []),
    }

    tenant.default_locale = default
    tenant.supported_locales = supported

    AuditService(session).record(
        ctx,
        action="tenants.tenant.languages_set",
        object_type="tenant",
        object_id=tenant.id,
        before=before,
        after={"default_locale": default, "supported_locales": supported},
    )
    await session.flush()

    removed = set(before["supported_locales"]) - set(supported)
    if removed:
        # Worth a log line: the club's site stops serving those languages from
        # this moment, and somebody will ask why.
        log.info(
            "tenant_languages_removed",
            tenant_id=str(tenant.id),
            removed=sorted(removed),
        )
    return tenant
