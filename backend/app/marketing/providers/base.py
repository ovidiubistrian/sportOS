"""How an email leaves the building.

One interface, two implementations, chosen by configuration. The point of the
seam is not that swapping providers is likely — it is that the club's data
model must not learn anything from the provider. A campaign records that an
address was written to and what happened; whether that went through a relay in
the club's own basement or through Mailgun's API is not the campaign's business.

SMTP is what ships. Mailgun is written and tested against a fake, and stays off
until somebody sets a key: a delivery provider with a bill attached should not
start working because a dependency happened to be installed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.core.errors import DomainError


class EmailUndeliverable(DomainError):
    """The provider refused. Recorded against the recipient, never fatal."""

    code, status = "EMAIL_UNDELIVERABLE", 502
    default_message = "That message could not be sent."


class EmailNotConfigured(DomainError):
    code, status = "EMAIL_NOT_CONFIGURED", 503
    default_message = "Email sending is not configured yet."


@dataclass(frozen=True, slots=True)
class Message:
    to: str
    subject: str
    html: str
    text: str
    from_name: str
    from_email: str
    reply_to: str | None = None
    # Unsubscribe belongs in a header as well as in the body: every serious
    # mailbox provider surfaces it as a one-click button, and a list that is
    # easy to leave is one that stays deliverable.
    list_unsubscribe: str | None = None


class EmailProvider(Protocol):
    name: str

    async def send(self, message: Message) -> None:
        """Deliver one message, or raise `EmailUndeliverable`."""
        ...
