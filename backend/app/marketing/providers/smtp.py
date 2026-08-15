"""SMTP, which is what a club already has.

Most Romanian clubs have a mailbox at their hosting provider and nothing else,
so this is the implementation that ships enabled. It is deliberately plain:
connect, authenticate if credentials exist, send, disconnect. No pooling, no
persistent connection — a campaign sends in batches with a small delay, and a
connection held open across minutes is a connection a relay will drop halfway.
"""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage
from email.policy import SMTP as SMTP_POLICY
from email.utils import formataddr

import structlog

from app.core.config import settings
from app.marketing.providers.base import EmailUndeliverable, Message

log = structlog.get_logger(__name__)


# `refold_source="none"` matters more than it looks. Python folds long header
# values into RFC 2047 encoded words, and a `List-Unsubscribe` that arrives as
# `=?utf-8?q?=3Chttp...` is one no mailbox provider will parse — which loses
# the one-click unsubscribe button that keeps a sender out of the spam folder.
# `max_line_length=0` is the part that actually stops it. Python folds any
# header longer than 78 characters into RFC 2047 encoded words, and a
# `List-Unsubscribe` that arrives as `=?utf-8?q?=3Chttp...` is one no mailbox
# provider will parse — which loses the one-click unsubscribe button that keeps
# a new sender out of the spam folder. Unfolded is legal and understood.
_POLICY = SMTP_POLICY.clone(refold_source="none", max_line_length=0)


def _build(message: Message) -> EmailMessage:
    mail = EmailMessage(policy=_POLICY)
    mail["Subject"] = message.subject
    mail["From"] = formataddr((message.from_name, message.from_email))
    mail["To"] = message.to
    if message.reply_to:
        mail["Reply-To"] = message.reply_to
    if message.list_unsubscribe:
        mail["List-Unsubscribe"] = f"<{message.list_unsubscribe}>"
        # Tells the mailbox provider the link is safe to POST for one-click
        # unsubscribe, which is what keeps a club out of the spam folder.
        mail["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

    # Plain text first, HTML as the alternative: that is the order the standard
    # wants, and a text part is what stops a club's newsletter scoring as spam.
    mail.set_content(message.text)
    mail.add_alternative(message.html, subtype="html")
    return mail


def _send_blocking(message: Message) -> None:
    mail = _build(message)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as client:
            if settings.smtp_use_tls:
                client.starttls()
            if settings.smtp_username:
                client.login(settings.smtp_username, settings.smtp_password.get_secret_value())
            client.send_message(mail)
    except (smtplib.SMTPException, OSError) as exc:
        # Never the message body in a log line: it is somebody's mail.
        raise EmailUndeliverable(str(exc)[:200]) from exc


class SmtpProvider:
    name = "SMTP"

    async def send(self, message: Message) -> None:
        # `smtplib` is blocking, so it goes to a thread rather than stalling the
        # event loop for the length of a relay's handshake.
        await asyncio.to_thread(_send_blocking, message)
