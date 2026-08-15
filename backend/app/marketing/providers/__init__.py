"""Choosing a provider.

Configuration decides, and the default is the one a club already owns. Mailgun
is only reachable once a key exists — an integration that switches itself on
because a library is installed is an integration that sends a club's first
campaign through an account nobody has paid for.
"""

from __future__ import annotations

from app.core.config import settings
from app.marketing.providers.base import (
    EmailNotConfigured,
    EmailProvider,
    EmailUndeliverable,
    Message,
)
from app.marketing.providers.mailgun import MailgunProvider
from app.marketing.providers.smtp import SmtpProvider

__all__ = [
    "EmailNotConfigured",
    "EmailProvider",
    "EmailUndeliverable",
    "Message",
    "current_provider",
    "provider_name",
]


def current_provider() -> EmailProvider:
    wants_mailgun = settings.email_provider.upper() == "MAILGUN"
    has_key = bool(settings.mailgun_api_key.get_secret_value())
    if wants_mailgun and has_key:
        return MailgunProvider()
    return SmtpProvider()


def provider_name() -> str:
    return current_provider().name
