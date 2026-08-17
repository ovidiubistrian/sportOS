"""Recording what was said to a payment gateway.

Two promises, and they pull in opposite directions.

The record must survive the request. A registration that the gateway refused
has usually just failed the request too, and if the journal shared that unit of
work it would roll back with it — destroying the evidence of exactly the call
worth keeping. So each line is written in its own transaction, the way
`record_access` already is for sensitive reads.

The record must never cost a payment. If writing it fails, for any reason, the
payment carries on and the failure goes to the log. A club losing a sale
because we could not file the paperwork is the worse outcome by a distance.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID

from app.payments.models import PaymentProviderCall

log = logging.getLogger(__name__)

# Only secrets are removed. Everything else — the amount, the order number, the
# buyer's details, the gateway's own error text — stays exactly as it went,
# because being able to say "this is what we sent" is the entire point.
_SECRET_NAME = re.compile(r"(?i)^(authorization|password|secret|api[_-]?key|token)$")
_SECRET_PREFIX = ("Basic ", "Bearer ")

REDACTED = "[redacted]"


def redact(value: Any) -> Any:
    """Replace secrets, keep the shape."""
    if isinstance(value, dict):
        return {
            key: REDACTED if isinstance(key, str) and _SECRET_NAME.match(key) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        for prefix in _SECRET_PREFIX:
            if value.startswith(prefix):
                return f"{prefix}{REDACTED}"
    return value


def _jsonable(value: Any) -> Any:
    """JSONB takes what it takes; anything else becomes its repr rather than
    an exception at the very end of a payment."""
    try:
        import json

        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return {"unserialisable": str(value)[:1000]}


class PaymentJournal:
    """Writes one line per gateway call, for one tenant.

    Held by a provider for the length of a request. `order_ref` is optional
    because the settings screen tests credentials with no purchase in hand —
    the line still belongs to the tenant, and is still worth keeping.
    """

    def __init__(self, tenant_id: UUID | None, order_ref: str | None = None) -> None:
        self.tenant_id = tenant_id
        self.order_ref = order_ref

    async def record(
        self,
        *,
        provider: str,
        path: str,
        sent: Any,
        received: Any,
        http_status: int | None,
        error_code: str | None,
        error_message: str | None,
        ok: bool,
        latency_ms: int | None,
        provider_order_id: str | None,
    ) -> None:
        if self.tenant_id is None:
            # Nothing to scope the row to, and a row scoped to nothing can
            # never be found again. Dropping it beats filing it under a
            # sentinel that looks like a tenant and is not.
            return
        try:
            from app.core.db import tenant_session

            async with tenant_session(self.tenant_id) as session:
                session.add(
                    PaymentProviderCall(
                        tenant_id=self.tenant_id,
                        provider=provider,
                        endpoint=path,
                        order_ref=self.order_ref,
                        provider_order_id=provider_order_id,
                        http_status=http_status,
                        error_code=error_code,
                        error_message=(error_message or None),
                        ok=ok,
                        latency_ms=latency_ms,
                        sent=_jsonable(redact(sent)),
                        received=_jsonable(redact(received)),
                    )
                )
        except Exception:
            log.exception("payment journal write failed, payment continues")
