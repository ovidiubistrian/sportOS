"""Working out who to write to, what to say, and how to let them leave.

Three jobs, and the first one carries the whole module's conscience.

**The audience** is computed, never stored. Two pools — newsletter subscribers
and supporters who ticked the marketing box — each with its own consent
timestamp, unioned by address so somebody in both is written to once. Anybody
who has unsubscribed is excluded at the source rather than filtered later,
because a filter is something a future refactor can forget.

**The letter** is rendered from typed blocks into HTML and plain text, in the
club's own colours. Email is not the web: no external stylesheet survives, so
every rule is inlined, and the layout is a table because that is still what
Outlook understands. The blocks are the same ones the CMS uses, which means
nothing an author types can become markup.

**The way out** is a signed link that needs no database lookup and cannot be
guessed. It is in the body and in the `List-Unsubscribe` header, because a list
that is easy to leave is a list that keeps arriving in inboxes.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.fans.models import NewsletterSubscriber
from app.fans.supporter_models import Supporter
from app.marketing.models import Campaign, CampaignRecipient, EmailTemplate
from app.marketing.providers import Message
from app.tenants.branding_models import ClubBranding
from app.tenants.models import Club

log = structlog.get_logger(__name__)


# --- who ---------------------------------------------------------------------


async def audience(
    session: AsyncSession, *, club_id: UUID, pool: str, locale: str | None
) -> list[tuple[str, str]]:
    """`(email, source)` for everybody this campaign may lawfully reach.

    Deduplicated by address, keeping whichever pool found them first, so a
    supporter who also signed up in the footer gets one email and not two.
    """
    found: dict[str, str] = {}

    if pool in ("NEWSLETTER", "EVERYONE"):
        stmt = select(NewsletterSubscriber.email, NewsletterSubscriber.locale).where(
            NewsletterSubscriber.club_id == club_id,
            NewsletterSubscriber.unsubscribed_at.is_(None),
        )
        for email, row_locale in await session.execute(stmt):
            if locale and row_locale and row_locale != locale:
                continue
            found.setdefault(str(email).lower(), "NEWSLETTER")

    if pool in ("SUPPORTERS", "EVERYONE"):
        stmt = select(Supporter.email, Supporter.locale).where(
            Supporter.club_id == club_id,
            # The consent timestamp, not a flag. Having an account is not
            # agreeing to be marketed at, and this is the line that keeps those
            # two facts apart.
            Supporter.marketing_opt_in_at.isnot(None),
            Supporter.email.isnot(None),
        )
        for email, row_locale in await session.execute(stmt):
            if locale and row_locale and row_locale != locale:
                continue
            found.setdefault(str(email).lower(), "SUPPORTERS")

    return sorted(found.items())


# --- the way out --------------------------------------------------------------


def unsubscribe_token(club_id: UUID, email: str) -> str:
    """A signature, not an identifier.

    Stateless on purpose: no row to create when sending, none to clean up
    afterwards, and nothing to leak. Keyed on the club so a token from one
    club cannot unsubscribe somebody from another.
    """
    material = f"{club_id}:{email.lower()}".encode()
    return hmac.new(
        settings.secret_key.get_secret_value().encode(), material, hashlib.sha256
    ).hexdigest()[:32]


def token_matches(club_id: UUID, email: str, token: str) -> bool:
    return hmac.compare_digest(unsubscribe_token(club_id, email), token)


def unsubscribe_url(base_url: str, club_id: UUID, email: str) -> str:
    token = unsubscribe_token(club_id, email)
    return f"{base_url.rstrip('/')}/dezabonare?e={email}&t={token}"


# --- the letter ---------------------------------------------------------------


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _blocks_to_html(blocks: list[dict], brand: str) -> str:
    """The same typed blocks the CMS uses, as email-safe HTML.

    Every style is inline. A `<style>` block is stripped by Gmail, and a class
    means nothing in Outlook — so the rules travel with the elements or they do
    not travel at all.
    """
    out: list[str] = []
    for block in blocks or []:
        kind = block.get("type")
        if kind == "heading":
            level = 2 if block.get("level", 2) == 2 else 3
            size = "22px" if level == 2 else "18px"
            out.append(
                f'<h{level} style="margin:28px 0 10px;font-size:{size};line-height:1.25;'
                f'color:#111;font-weight:700">{_escape(block.get("text", ""))}</h{level}>'
            )
        elif kind == "quote":
            attribution = block.get("attribution")
            credit = (
                f'<br><span style="color:#666;font-size:14px">— {_escape(attribution)}</span>'
                if attribution
                else ""
            )
            quote = _escape(block.get("text", ""))
            out.append(
                f'<blockquote style="margin:20px 0;padding:12px 18px;'
                f'border-left:3px solid {brand};color:#333;font-style:italic">'
                f"{quote}{credit}</blockquote>"
            )
        elif kind == "list":
            tag = "ol" if block.get("ordered") else "ul"
            items = "".join(
                f'<li style="margin:0 0 6px">{_escape(item)}</li>'
                for item in block.get("items", [])
            )
            style = "margin:14px 0;padding-left:22px;color:#333"
            out.append(f'<{tag} style="{style}">{items}</{tag}>')
        else:
            out.append(
                '<p style="margin:0 0 14px;font-size:16px;line-height:1.6;color:#333">'
                f"{_escape(block.get('text', ''))}</p>"
            )
    return "\n".join(out)


def _blocks_to_text(blocks: list[dict]) -> str:
    lines: list[str] = []
    for block in blocks or []:
        kind = block.get("type")
        if kind == "list":
            lines.extend(f"- {item}" for item in block.get("items", []))
        elif kind == "quote":
            lines.append(f'"{block.get("text", "")}"')
            if block.get("attribution"):
                lines.append(f"  — {block['attribution']}")
        else:
            lines.append(str(block.get("text", "")))
        lines.append("")
    return "\n".join(lines).strip()


def render(
    *,
    template: EmailTemplate,
    club: Club,
    branding: ClubBranding | None,
    site_url: str,
    unsubscribe: str,
) -> tuple[str, str]:
    """`(html, text)` for one letter.

    A table, a 600px column and inline styles — the shape email has had for
    twenty years, because the clients that matter have not moved.
    """
    brand = (branding.color_primary if branding else "#1F4B99") or "#1F4B99"
    body_html = _blocks_to_html(template.blocks, brand)

    cta = ""
    if template.cta_label and template.cta_url:
        link = _escape(template.cta_url)
        button = (
            "display:inline-block;padding:13px 26px;color:#fff;"
            "text-decoration:none;font-weight:700;font-size:15px"
        )
        cta = (
            '<table role="presentation" cellpadding="0" cellspacing="0" style="margin:26px 0">'
            f'<tr><td style="background:{brand};border-radius:6px">'
            f'<a href="{link}" style="{button}">'
            f"{_escape(template.cta_label)}</a></td></tr></table>"
        )

    preheader = (
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0">'
        f"{_escape(template.preheader)}</div>"
        if template.preheader
        else ""
    )

    html = f"""<!doctype html>
<html lang="{club.default_locale or "ro"}">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_escape(template.subject)}</title></head>
<body style="margin:0;padding:0;background:#f4f5f7">
{preheader}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background:#f4f5f7">
<tr><td align="center" style="padding:28px 12px">
<table role="presentation" width="600" cellpadding="0" cellspacing="0"
       style="width:600px;max-width:100%;background:#fff;border-radius:12px;overflow:hidden;
              font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">
  <tr><td style="background:{brand};padding:22px 28px">
    <span style="color:#fff;font-size:17px;font-weight:700;letter-spacing:.02em">
      {_escape(club.display_name)}</span>
  </td></tr>
  <tr><td style="padding:28px">
    {body_html}
    {cta}
  </td></tr>
  <tr><td style="padding:18px 28px;border-top:1px solid #eceef1;background:#fafbfc">
    <p style="margin:0 0 6px;font-size:12px;color:#6b7280">
      {_escape(club.display_name)} · <a href="{_escape(site_url)}"
      style="color:#6b7280">{_escape(site_url)}</a></p>
    <p style="margin:0;font-size:12px;color:#9aa1ab">
      <a href="{_escape(unsubscribe)}" style="color:#9aa1ab">Dezabonare</a>
    </p>
  </td></tr>
</table>
</td></tr></table>
</body></html>"""

    text = (
        f"{club.display_name}\n\n"
        f"{_blocks_to_text(template.blocks)}\n\n"
        + (f"{template.cta_label}: {template.cta_url}\n\n" if template.cta_url else "")
        + f"{site_url}\nDezabonare: {unsubscribe}\n"
    )
    return html, text


# --- sending ------------------------------------------------------------------

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


async def prepare(
    session: AsyncSession, campaign: Campaign, recipients: list[tuple[str, str]]
) -> int:
    """Write the recipient list before a single message goes out.

    This is what makes a send resumable and safe to retry: the unique
    constraint on (campaign, email) means a second attempt cannot write to
    anybody twice, and a crash halfway leaves a list that says exactly who was
    already reached.
    """
    existing = {
        str(row).lower()
        for row in await session.scalars(
            select(CampaignRecipient.email).where(CampaignRecipient.campaign_id == campaign.id)
        )
    }

    added = 0
    for email, source in recipients:
        if email in existing or not _EMAIL.match(email):
            continue
        session.add(
            CampaignRecipient(
                tenant_id=campaign.tenant_id,
                campaign_id=campaign.id,
                email=email,
                source=source,
                status="PENDING",
            )
        )
        added += 1

    await session.flush()
    campaign.total = len(existing) + added
    return added


def message_for(
    *,
    to: str,
    subject: str,
    html: str,
    text: str,
    club: Club,
    unsubscribe: str,
) -> Message:
    return Message(
        to=to,
        subject=subject,
        html=html,
        text=text,
        from_name=club.display_name,
        from_email=settings.email_from_address,
        reply_to=None,
        list_unsubscribe=unsubscribe,
    )


def now() -> datetime:
    return datetime.now(UTC)
