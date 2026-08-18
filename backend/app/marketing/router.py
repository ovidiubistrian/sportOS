"""The club's newsletter, from the club's side.

Templates are edited; campaigns are aimed and sent. The one endpoint worth
reading twice is `send`, which does the work in a deliberate order: resolve the
audience, write every recipient down, and only then start delivering. A crash
at any point after the second step is resumable, and a second press of the
button reaches nobody twice.

Sending is inline rather than queued. A club's list is hundreds of addresses,
not millions; a background worker would be a second moving part to operate for
a job that finishes in seconds. When a club outgrows that, the relay it already
runs is where this moves — the recipient table is already the queue.
"""

from __future__ import annotations

import asyncio
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import func, select

from app.api.deps import Db, Requires
from app.audit.service import AuditService
from app.core.context import RequestContext
from app.core.db import tenant_session
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.marketing import service
from app.marketing.models import (
    AUDIENCES,
    CAMPAIGN_KINDS,
    Campaign,
    CampaignRecipient,
    EmailTemplate,
)
from app.marketing.providers import EmailUndeliverable, current_provider, provider_name
from app.tenants.branding_models import ClubBranding
from app.tenants.models import Club, ClubDomain

log = structlog.get_logger(__name__)

router = APIRouter(tags=["marketing"])

READ = "marketing.campaign.read"
WRITE = "marketing.campaign.manage"

# Pause between messages. Not a rate limit so much as good manners: a relay
# that suddenly sees four hundred messages in two seconds from a new sender
# treats it exactly as it would treat a spammer.
SEND_DELAY_SECONDS = 0.08


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    club_id: UUID
    key: str
    name: str
    subject: str
    preheader: str | None
    blocks: list
    cta_label: str | None
    cta_url: str | None
    locale: str | None
    is_active: bool


class TemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    club_id: UUID
    key: str = Field(min_length=2, max_length=48, pattern=r"^[a-z0-9-]+$")
    name: str = Field(min_length=2, max_length=120)
    subject: str = Field(min_length=2, max_length=200)
    preheader: str | None = Field(default=None, max_length=200)
    blocks: list = Field(default_factory=list)
    cta_label: str | None = Field(default=None, max_length=48)
    cta_url: str | None = Field(default=None, max_length=500)
    locale: str | None = Field(default=None, max_length=10)


class TemplateChanges(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=120)
    subject: str | None = Field(default=None, min_length=2, max_length=200)
    preheader: str | None = Field(default=None, max_length=200)
    blocks: list | None = None
    cta_label: str | None = Field(default=None, max_length=48)
    cta_url: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    club_id: UUID
    template_id: UUID
    name: str
    kind: str
    audience: str
    locale: str | None
    status: str
    total: int
    sent: int
    failed: int
    opened: int
    unsubscribed: int
    error: str | None


class CampaignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    club_id: UUID
    template_id: UUID
    name: str = Field(min_length=2, max_length=160)
    kind: str = "NEWS"
    audience: str = "NEWSLETTER"
    locale: str | None = Field(default=None, max_length=10)

    @field_validator("audience")
    @classmethod
    def _known_audience(cls, value: str) -> str:
        if value not in AUDIENCES:
            raise ValueError(f"must be one of {', '.join(AUDIENCES)}")
        return value

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, value: str) -> str:
        if value not in CAMPAIGN_KINDS:
            raise ValueError(f"must be one of {', '.join(CAMPAIGN_KINDS)}")
        return value


class AudienceOut(BaseModel):
    """How many people this would reach, before anybody presses send."""

    total: int
    newsletter: int
    supporters: int
    provider: str


class PreviewOut(BaseModel):
    subject: str
    html: str
    text: str


class TestSendIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to: EmailStr


async def _club(db: Db, ctx: RequestContext, club_id: UUID) -> Club:
    club = await db.scalar(select(Club).where(Club.id == club_id, Club.tenant_id == ctx.tenant))
    if club is None:
        raise NotFound(object_type="club", object_id=str(club_id))
    return club


async def _site_url(db: Db, club: Club) -> str:
    """The club's own address, for the links in its own email."""
    host = await db.scalar(
        select(ClubDomain.hostname).where(ClubDomain.club_id == club.id).limit(1)
    )
    return f"http://{host}" if host else "http://localhost"


# --- templates ----------------------------------------------------------------


@router.get("/email-templates", response_model=list[TemplateOut], summary="Letters")
async def list_templates(
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(READ))],
    club_id: Annotated[UUID | None, Query()] = None,
) -> list[TemplateOut]:
    stmt = select(EmailTemplate).where(EmailTemplate.tenant_id == ctx.tenant)
    if club_id:
        stmt = stmt.where(EmailTemplate.club_id == club_id)
    rows = await db.scalars(stmt.order_by(EmailTemplate.name))
    return [TemplateOut.model_validate(row) for row in rows]


@router.post(
    "/email-templates",
    response_model=TemplateOut,
    status_code=status.HTTP_201_CREATED,
    summary="Write a letter",
)
async def create_template(
    payload: TemplateIn,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(WRITE))],
) -> TemplateOut:
    await _club(db, ctx, payload.club_id)

    clash = await db.scalar(
        select(EmailTemplate.id).where(
            EmailTemplate.tenant_id == ctx.tenant,
            EmailTemplate.club_id == payload.club_id,
            EmailTemplate.key == payload.key,
        )
    )
    if clash:
        raise Conflict("A template with that key already exists.")

    template = EmailTemplate(tenant_id=ctx.tenant, **payload.model_dump())
    db.add(template)
    await db.flush()

    AuditService(db).record(
        ctx,
        action="marketing.template.create",
        object_type="email_template",
        object_id=template.id,
        club_id=payload.club_id,
        after={"key": payload.key},
    )
    return TemplateOut.model_validate(template)


@router.patch(
    "/email-templates/{template_id}", response_model=TemplateOut, summary="Edit a letter"
)
async def update_template(
    template_id: UUID,
    payload: TemplateChanges,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(WRITE))],
) -> TemplateOut:
    template = await db.scalar(
        select(EmailTemplate).where(
            EmailTemplate.id == template_id, EmailTemplate.tenant_id == ctx.tenant
        )
    )
    if template is None:
        raise NotFound(object_type="email_template", object_id=str(template_id))

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(template, field, value)
    return TemplateOut.model_validate(template)


@router.get(
    "/email-templates/{template_id}/preview",
    response_model=PreviewOut,
    summary="See the letter as it will arrive",
)
async def preview(
    template_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(READ))],
) -> PreviewOut:
    """Rendered with a real unsubscribe link, so the preview is the article.

    A preview that skips the footer is a preview that hides the one part most
    likely to be wrong.
    """
    template = await db.scalar(
        select(EmailTemplate).where(
            EmailTemplate.id == template_id, EmailTemplate.tenant_id == ctx.tenant
        )
    )
    if template is None:
        raise NotFound(object_type="email_template", object_id=str(template_id))

    club = await _club(db, ctx, template.club_id)
    branding = await db.scalar(select(ClubBranding).where(ClubBranding.club_id == club.id))
    site = await _site_url(db, club)
    html, text = service.render(
        template=template,
        club=club,
        branding=branding,
        site_url=site,
        unsubscribe=service.unsubscribe_url(site, club.id, "exemplu@email.ro"),
    )
    return PreviewOut(subject=template.subject, html=html, text=text)


# --- campaigns ----------------------------------------------------------------


@router.get("/campaigns", response_model=list[CampaignOut], summary="Campaigns")
async def list_campaigns(
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(READ))],
    club_id: Annotated[UUID | None, Query()] = None,
) -> list[CampaignOut]:
    stmt = select(Campaign).where(Campaign.tenant_id == ctx.tenant)
    if club_id:
        stmt = stmt.where(Campaign.club_id == club_id)
    rows = await db.scalars(stmt.order_by(Campaign.created_at.desc()).limit(50))
    return [CampaignOut.model_validate(row) for row in rows]


@router.get("/campaigns/audience", response_model=AudienceOut, summary="Who this reaches")
async def audience_size(
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(READ))],
    club_id: Annotated[UUID, Query()],
    pool: Annotated[str, Query()] = "NEWSLETTER",
    locale: Annotated[str | None, Query()] = None,
) -> AudienceOut:
    """Asked before sending, and worth asking: a club should never press send
    without knowing whether it is writing to nine people or nine hundred."""
    await _club(db, ctx, club_id)
    people = await service.audience(db, club_id=club_id, pool=pool, locale=locale)
    return AudienceOut(
        total=len(people),
        newsletter=sum(1 for _, source in people if source == "NEWSLETTER"),
        supporters=sum(1 for _, source in people if source == "SUPPORTERS"),
        provider=provider_name(),
    )


@router.post(
    "/campaigns",
    response_model=CampaignOut,
    status_code=status.HTTP_201_CREATED,
    summary="Plan a campaign",
)
async def create_campaign(
    payload: CampaignIn,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(WRITE))],
) -> CampaignOut:
    await _club(db, ctx, payload.club_id)
    template = await db.scalar(
        select(EmailTemplate).where(
            EmailTemplate.id == payload.template_id,
            EmailTemplate.tenant_id == ctx.tenant,
        )
    )
    if template is None:
        raise NotFound(object_type="email_template", object_id=str(payload.template_id))

    campaign = Campaign(tenant_id=ctx.tenant, created_by=ctx.actor_id, **payload.model_dump())
    db.add(campaign)
    await db.flush()
    return CampaignOut.model_validate(campaign)


@router.post(
    "/campaigns/{campaign_id}/test",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Send one copy to yourself",
)
async def send_test(
    campaign_id: UUID,
    payload: TestSendIn,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(WRITE))],
) -> None:
    campaign = await db.scalar(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.tenant_id == ctx.tenant)
    )
    if campaign is None:
        raise NotFound(object_type="campaign", object_id=str(campaign_id))

    template = await db.get(EmailTemplate, campaign.template_id)
    club = await _club(db, ctx, campaign.club_id)
    branding = await db.scalar(select(ClubBranding).where(ClubBranding.club_id == club.id))
    site = await _site_url(db, club)

    if template is None:
        raise NotFound(object_type="email_template", object_id=str(campaign.template_id))

    unsubscribe = service.unsubscribe_url(site, club.id, str(payload.to))
    html, text = service.render(
        template=template, club=club, branding=branding, site_url=site, unsubscribe=unsubscribe
    )
    await current_provider().send(
        service.message_for(
            to=str(payload.to),
            subject=f"[test] {template.subject}",
            html=html,
            text=text,
            club=club,
            unsubscribe=unsubscribe,
        )
    )


@router.post("/campaigns/{campaign_id}/send", response_model=CampaignOut, summary="Send it")
async def send_campaign(
    campaign_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(WRITE))],
) -> CampaignOut:
    """Resolve, record, then deliver — in that order.

    Recipients are written and committed before the first message leaves, so a
    failure halfway through is a list of who was already reached rather than a
    guess. Pressing send twice is safe for the same reason.
    """
    campaign = await db.scalar(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.tenant_id == ctx.tenant)
    )
    if campaign is None:
        raise NotFound(object_type="campaign", object_id=str(campaign_id))
    if campaign.status in ("SENDING", "SENT"):
        raise Conflict("That campaign has already been sent.")

    template = await db.get(EmailTemplate, campaign.template_id)
    if template is None:
        raise NotFound(object_type="email_template", object_id=str(campaign.template_id))

    club = await _club(db, ctx, campaign.club_id)
    branding = await db.scalar(select(ClubBranding).where(ClubBranding.club_id == club.id))
    site = await _site_url(db, club)

    people = await service.audience(
        db, club_id=club.id, pool=campaign.audience, locale=campaign.locale
    )
    if not people:
        raise ValidationFailed("Nobody has agreed to hear from the club yet.", field="audience")

    # The recipient list is written in its own transaction, which commits
    # before a single message leaves. It cannot be the request's transaction:
    # committing that one mid-request would end the tenant context the rest of
    # the handler still needs — row-level security is set per transaction, so
    # the next insert would be refused by the database.
    async with tenant_session(ctx.tenant) as write:
        writing = await write.get(Campaign, campaign.id)
        if writing is not None:
            await service.prepare(write, writing, people)
            writing.status = "SENDING"
            writing.started_at = service.now()

    await db.refresh(campaign)

    provider = current_provider()
    pending = list(
        await db.scalars(
            select(CampaignRecipient).where(
                CampaignRecipient.campaign_id == campaign.id,
                CampaignRecipient.status == "PENDING",
            )
        )
    )

    sent = failed = 0
    for recipient in pending:
        unsubscribe = service.unsubscribe_url(site, club.id, recipient.email)
        html, text = service.render(
            template=template,
            club=club,
            branding=branding,
            site_url=site,
            unsubscribe=unsubscribe,
        )
        try:
            await provider.send(
                service.message_for(
                    to=recipient.email,
                    subject=template.subject,
                    html=html,
                    text=text,
                    club=club,
                    unsubscribe=unsubscribe,
                )
            )
            recipient.status = "SENT"
            recipient.sent_at = service.now()
            sent += 1
        except EmailUndeliverable as exc:
            # One bad address does not stop a campaign. It is recorded against
            # the recipient so the club can see exactly which ones bounced.
            recipient.status = "FAILED"
            recipient.error = str(exc)[:300]
            failed += 1

        await asyncio.sleep(SEND_DELAY_SECONDS)

    campaign.sent = sent
    campaign.failed = failed
    campaign.finished_at = service.now()
    campaign.status = "SENT" if sent else "FAILED"

    AuditService(db).record(
        ctx,
        action="marketing.campaign.send",
        object_type="campaign",
        object_id=campaign.id,
        club_id=club.id,
        after={"sent": sent, "failed": failed, "provider": provider.name},
    )
    log.info(
        "campaign_sent",
        campaign_id=str(campaign.id),
        sent=sent,
        failed=failed,
        provider=provider.name,
    )
    return CampaignOut.model_validate(campaign)


@router.get(
    "/campaigns/{campaign_id}/recipients",
    response_model=dict,
    summary="What happened to each address",
)
async def recipients(
    campaign_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(READ))],
) -> dict:
    rows = await db.execute(
        select(CampaignRecipient.status, func.count())
        .where(
            CampaignRecipient.tenant_id == ctx.tenant,
            CampaignRecipient.campaign_id == campaign_id,
        )
        .group_by(CampaignRecipient.status)
    )
    return {status_name: int(count) for status_name, count in rows}
