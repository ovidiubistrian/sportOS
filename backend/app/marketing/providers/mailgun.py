"""Mailgun, written and ready, switched off.

Not used yet, and deliberately not a stub: the day a club outgrows its host's
relay — bounce handling, reputation, a hundred thousand addresses — the change
is one setting, not a project. Until `MAILGUN_API_KEY` is set the factory never
returns this, so an unused integration cannot start sending by accident.

The one thing it does that SMTP cannot is report a provider message id, which
is what later lets a bounce webhook find the recipient it belongs to.
"""

from __future__ import annotations

import httpx
import structlog

from app.core.config import settings
from app.marketing.providers.base import EmailNotConfigured, EmailUndeliverable, Message

log = structlog.get_logger(__name__)


class MailgunProvider:
    name = "MAILGUN"

    async def send(self, message: Message) -> None:
        key = settings.mailgun_api_key.get_secret_value()
        domain = settings.mailgun_domain
        if not key or not domain:
            raise EmailNotConfigured()

        data = {
            "from": f"{message.from_name} <{message.from_email}>",
            "to": message.to,
            "subject": message.subject,
            "text": message.text,
            "html": message.html,
        }
        if message.reply_to:
            data["h:Reply-To"] = message.reply_to
        if message.list_unsubscribe:
            data["h:List-Unsubscribe"] = f"<{message.list_unsubscribe}>"
            data["h:List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(
                    f"{settings.mailgun_base_url}/{domain}/messages",
                    auth=("api", key),
                    data=data,
                )
        except httpx.HTTPError as exc:
            raise EmailUndeliverable(str(exc)[:200]) from exc

        if response.status_code >= 400:
            # The body can echo the recipient, so only the status is logged.
            log.warning("mailgun_rejected", status=response.status_code)
            raise EmailUndeliverable(f"Mailgun returned {response.status_code}.")
