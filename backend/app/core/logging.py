"""Structured logging.

JSON in every environment except a developer's terminal. Correlation ids and
tenant context are bound automatically so no call site has to remember them.

PII does not go in logs. Emails and names are hashed by the redaction processor
if they appear in an event's fields; the raw values stay in the database where
access is controlled and audited.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sys
from typing import Any

import structlog

from app.core.config import settings
from app.core.context import current_request_id, current_tenant_id_optional

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

# Field names whose values are never logged, whatever they contain. Grouped by
# kind — credentials, then payment, then clinical — so a gap is visible.
# fmt: off
_FORBIDDEN_KEYS = frozenset(
    {
        "password", "secret", "token", "access_token", "refresh_token",
        "authorization", "api_key", "client_secret", "card", "pan", "cvc",
        "iban", "diagnosis", "medical_note",
    }
)
# fmt: on


def _hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()[:16]


def _redact(_logger: Any, _name: str, event: dict[str, Any]) -> dict[str, Any]:
    for key, value in list(event.items()):
        if key.lower() in _FORBIDDEN_KEYS:
            event[key] = "[redacted]"
        elif isinstance(value, str) and _EMAIL_RE.search(value):
            event[key] = _EMAIL_RE.sub(lambda m: _hash(m.group()), value)
    return event


def _bind_context(_logger: Any, _name: str, event: dict[str, Any]) -> dict[str, Any]:
    request_id = current_request_id()
    if request_id:
        event.setdefault("request_id", request_id)
    tenant_id = current_tenant_id_optional()
    if tenant_id:
        event.setdefault("tenant_id", str(tenant_id))
    return event


def configure_logging() -> None:
    renderer: Any = (
        structlog.dev.ConsoleRenderer()
        if settings.app_env == "development"
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _bind_context,
            _redact,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(settings.log_level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s", stream=sys.stdout, level=settings.log_level.upper()
    )
    for noisy in ("uvicorn.access", "sqlalchemy.engine.Engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
