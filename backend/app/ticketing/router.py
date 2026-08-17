"""The admin API: drawing a ground, putting a match on sale, holding seats back.

Thin by design. Every rule that matters — immutability after publish, snapshot
on creation, locking on hold — lives in the service layer, and these handlers
resolve a request, call one function and shape the answer. That is what lets
the browser scanner, the seed script and the tests all exercise the same
guarantees without going through HTTP.

Route order follows the stadium wizard, because the screens follow it too:
venue → configuration → stands and sectors → rows and seats → gates → price
zones → review and publish.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select

from app.api.deps import Db, Requires
from app.core.context import RequestContext
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.ticketing import event_service, inventory, issuing, pricing, venue_service
from app.ticketing.event_models import (
    Allocation,
    EventSeatInventory,
    PriceList,
    PriceRule,
    TicketedEvent,
    TicketType,
)
from app.ticketing.ticket_models import (
    SeasonPass,
    SeasonTicketEvent,
    SeasonTicketProduct,
    Ticket,
)
from app.ticketing.venue_models import (
    AccessZone,
    Gate,
    GateSection,
    PriceZone,
    Seat,
    SeatRow,
    Section,
    Stand,
    Venue,
    VenueConfiguration,
)

router = APIRouter(prefix="/ticketing", tags=["ticketing"])

VENUE_READ = "ticketing.venue.read"
VENUE_MANAGE = "ticketing.venue.manage"
VENUE_PUBLISH = "ticketing.venue.publish"
EVENT_READ = "ticketing.event.read"
EVENT_MANAGE = "ticketing.event.manage"
PRICING_MANAGE = "ticketing.pricing.manage"
ALLOCATION_MANAGE = "ticketing.allocation.manage"
ORDER_READ = "ticketing.order.read"
ORDER_MANAGE = "ticketing.order.manage"
SEASON_MANAGE = "ticketing.season.manage"
REPORT_READ = "ticketing.report.read"


# --- schemas ----------------------------------------------------------------


class VenueIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    club_id: UUID
    name: str = Field(min_length=1, max_length=160)
    code: str = Field(min_length=1, max_length=24)
    address: str | None = Field(default=None, max_length=240)
    city: str | None = Field(default=None, max_length=120)
    country_code: str = Field(default="RO", min_length=2, max_length=2)
    timezone: str = Field(default="Europe/Bucharest", max_length=64)
    currency: str = Field(default="RON", min_length=3, max_length=3)
    expected_capacity: int = Field(default=0, ge=0)
    pitch_orientation: str = "NORTH_SOUTH"
    cover_media_id: UUID | None = None


class VenueOut(BaseModel):
    id: UUID
    club_id: UUID
    name: str
    code: str
    address: str | None
    city: str | None
    country_code: str
    timezone: str
    currency: str
    expected_capacity: int
    pitch_orientation: str
    cover_media_id: UUID | None


class ConfigurationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    valid_from: date | None = None


class ConfigurationOut(BaseModel):
    id: UUID
    venue_id: UUID
    name: str
    version: int
    status: str
    valid_from: date | None
    total_capacity: int
    published_at: datetime | None
    forked_from_id: UUID | None


class StandIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=1, max_length=24)
    display_order: int = 0
    geometry: dict[str, Any] = Field(default_factory=dict)


class SectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=1, max_length=24)
    kind: Literal["RESERVED", "GENERAL_ADMISSION"] = "RESERVED"
    declared_capacity: int = Field(default=0, ge=0)
    price_zone_id: UUID | None = None
    display_order: int = 0
    geometry: dict[str, Any] = Field(default_factory=dict)


class PriceZoneIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    code: str = Field(min_length=1, max_length=24)
    colour: str = Field(default="#334155", max_length=9)
    display_order: int = 0


class GateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=1, max_length=24)
    kind: Literal["PUBLIC", "VIP", "MEDIA", "STAFF", "ACCESSIBLE", "AWAY"] = "PUBLIC"
    supporter_side: Literal["ANY", "HOME", "AWAY"] = "ANY"
    is_accessible: bool = False
    access_zone_id: UUID | None = None
    note: str | None = None
    section_ids: list[UUID] = Field(default_factory=list)


class SeatPlanIn(BaseModel):
    """What the row-and-seat generator is asked for."""

    model_config = ConfigDict(extra="forbid")

    row_count: int = Field(ge=1, le=200)
    seats_per_row: int = Field(ge=1, le=200)
    row_start_label: str = Field(default="A", max_length=4)
    row_label_style: Literal["ALPHABETIC", "NUMERIC"] = "ALPHABETIC"
    first_seat_number: int = Field(default=1, ge=0)
    direction: Literal["LEFT_TO_RIGHT", "RIGHT_TO_LEFT"] = "LEFT_TO_RIGHT"
    aisle_after: list[int] = Field(default_factory=list)
    wheelchair_seats: list[str] = Field(default_factory=list)
    companion_seats: list[str] = Field(default_factory=list)
    obstructed_seats: list[str] = Field(default_factory=list)
    blocked_seats: list[str] = Field(default_factory=list)
    # Regenerating destroys existing rows, so the caller has to mean it.
    replace: bool = False


class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    club_id: UUID
    venue_id: UUID
    configuration_id: UUID
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=200)
    kickoff_at: datetime
    doors_open_at: datetime | None = None
    match_id: UUID | None = None
    season_id: UUID | None = None
    opponent_name: str | None = Field(default=None, max_length=160)
    competition_label: str | None = Field(default=None, max_length=120)
    category: Literal["A", "B", "C"] = "B"
    is_public: bool = True
    currency: str = Field(default="RON", min_length=3, max_length=3)
    presale_start_at: datetime | None = None
    sales_start_at: datetime | None = None
    sales_end_at: datetime | None = None
    max_per_customer: int = Field(default=10, ge=1, le=100)
    avoid_orphan_seats: bool = False
    fee_per_ticket_minor: int = Field(default=0, ge=0)
    fee_per_order_minor: int = Field(default=0, ge=0)


class PriceRuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price_zone_code: str = Field(min_length=1, max_length=24)
    ticket_type_id: UUID
    amount_minor: int = Field(ge=0)
    vat_rate_bp: int = Field(default=0, ge=0, le=10000)
    vat_included: bool = True
    fee_minor: int = Field(default=0, ge=0)


class AllocationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["HARD_HOLD", "SOFT_ALLOCATION"]
    reason: str = "OTHER"
    name: str = Field(min_length=1, max_length=160)
    owner_name: str | None = Field(default=None, max_length=160)
    access_code: str | None = Field(default=None, max_length=32)
    expires_at: datetime | None = None
    note: str | None = None
    inventory_ids: list[UUID] = Field(default_factory=list)
    # Or take a whole sector at once, which is what closing a stand means.
    section_id: UUID | None = None


class TicketTypeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    code: str = Field(min_length=1, max_length=24)
    description: str | None = Field(default=None, max_length=240)
    requires_proof: bool = False
    is_complimentary: bool = False
    is_away: bool = False
    display_order: int = 0
    is_active: bool = True


class SeasonProductIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    club_id: UUID
    configuration_id: UUID
    name: str = Field(min_length=1, max_length=160)
    description: str | None = None
    price_minor: int = Field(ge=0)
    currency: str = Field(default="RON", min_length=3, max_length=3)
    season_id: UUID | None = None
    eligibility: Literal["PUBLIC", "MEMBERS", "RENEWAL_ONLY"] = "PUBLIC"
    sales_start_at: datetime | None = None
    sales_end_at: datetime | None = None
    renewal_deadline: date | None = None
    is_transferable: bool = True
    event_ids: list[UUID] = Field(default_factory=list)


class SeasonPassIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seat_id: UUID
    holder_name: str = Field(min_length=1, max_length=160)
    holder_email: str | None = Field(default=None, max_length=320)


# --- venues -----------------------------------------------------------------


@router.get("/venues", response_model=list[VenueOut], summary="Stadiums")
async def list_venues(
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(VENUE_READ))],
    club_id: UUID | None = None,
) -> list[Venue]:
    query = select(Venue).where(Venue.tenant_id == ctx.tenant)
    if club_id is not None:
        query = query.where(Venue.club_id == club_id)
    return list(await db.scalars(query.order_by(Venue.name)))


@router.post("/venues", response_model=VenueOut, status_code=201, summary="Add a stadium")
async def create_venue(
    payload: VenueIn,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(VENUE_MANAGE))],
) -> Venue:
    venue = Venue(tenant_id=ctx.tenant, **payload.model_dump())
    db.add(venue)
    await db.flush()
    return venue


@router.patch("/venues/{venue_id}", response_model=VenueOut, summary="Edit a stadium")
async def update_venue(
    venue_id: UUID,
    payload: VenueIn,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(VENUE_MANAGE))],
) -> Venue:
    venue = await db.scalar(
        select(Venue).where(Venue.tenant_id == ctx.tenant, Venue.id == venue_id)
    )
    if venue is None:
        raise NotFound("That stadium does not exist.")
    for field, value in payload.model_dump().items():
        setattr(venue, field, value)
    await db.flush()
    return venue


# --- configurations ---------------------------------------------------------


@router.get(
    "/venues/{venue_id}/configurations",
    response_model=list[ConfigurationOut],
    summary="Stadium configurations",
)
async def list_configurations(
    venue_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(VENUE_READ))],
) -> list[VenueConfiguration]:
    return list(
        await db.scalars(
            select(VenueConfiguration)
            .where(
                VenueConfiguration.tenant_id == ctx.tenant,
                VenueConfiguration.venue_id == venue_id,
            )
            .order_by(VenueConfiguration.name, VenueConfiguration.version.desc())
        )
    )


@router.post(
    "/venues/{venue_id}/configurations",
    response_model=ConfigurationOut,
    status_code=201,
    summary="Start a configuration",
)
async def create_configuration(
    venue_id: UUID,
    payload: ConfigurationIn,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(VENUE_MANAGE))],
) -> VenueConfiguration:
    config = await venue_service.create_configuration(
        db,
        ctx.tenant,
        venue_id=venue_id,
        name=payload.name,
        created_by=ctx.actor_id,
    )
    config.valid_from = payload.valid_from
    await db.flush()
    return config


@router.post(
    "/configurations/{configuration_id}/fork",
    response_model=ConfigurationOut,
    status_code=201,
    summary="Edit a published configuration as a new version",
)
async def fork_configuration(
    configuration_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(VENUE_MANAGE))],
) -> VenueConfiguration:
    return await venue_service.fork(db, ctx.tenant, configuration_id, created_by=ctx.actor_id)


@router.get("/configurations/{configuration_id}/review", summary="Capacity and warnings")
async def review_configuration(
    configuration_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(VENUE_READ))],
) -> dict[str, Any]:
    result = await venue_service.review(db, ctx.tenant, configuration_id)
    return {
        "total_capacity": result.total_capacity,
        "reserved_seats": result.reserved_seats,
        "general_admission": result.general_admission,
        "blocked_seats": result.blocked_seats,
        "accessible_seats": result.accessible_seats,
        "by_stand": result.by_stand,
        "by_section": result.by_section,
        "publishable": result.publishable,
        "findings": [
            {
                "code": f.code,
                "message": f.message,
                "severity": f.severity,
                "subject": f.subject,
            }
            for f in result.findings
        ],
    }


@router.post(
    "/configurations/{configuration_id}/publish",
    response_model=ConfigurationOut,
    summary="Freeze a configuration",
)
async def publish_configuration(
    configuration_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(VENUE_PUBLISH))],
) -> VenueConfiguration:
    return await venue_service.publish(db, ctx.tenant, configuration_id)


@router.get("/configurations/{configuration_id}/layout", summary="The whole drawing")
async def configuration_layout(
    configuration_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(VENUE_READ))],
) -> dict[str, Any]:
    """Everything the editor draws, in one request.

    One round trip rather than a request per stand: the map is useless until
    all of it has arrived, so fetching it in pieces only shows the user a
    half-drawn stadium for longer.
    """
    return await event_service.build_snapshot_payload(db, ctx.tenant, configuration_id)


# --- stands, sectors, seats -------------------------------------------------


async def _editable(db: Db, tenant_id: UUID, configuration_id: UUID) -> VenueConfiguration:
    config = await venue_service.get_configuration(db, tenant_id, configuration_id)
    venue_service.assert_editable(config)
    return config


@router.post(
    "/configurations/{configuration_id}/stands", status_code=201, summary="Add a stand"
)
async def create_stand(
    configuration_id: UUID,
    payload: StandIn,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(VENUE_MANAGE))],
) -> dict[str, Any]:
    await _editable(db, ctx.tenant, configuration_id)
    stand = Stand(
        tenant_id=ctx.tenant, configuration_id=configuration_id, **payload.model_dump()
    )
    db.add(stand)
    await db.flush()
    return {"id": str(stand.id)}


@router.patch("/stands/{stand_id}", summary="Edit a stand")
async def update_stand(
    stand_id: UUID,
    payload: StandIn,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(VENUE_MANAGE))],
) -> dict[str, Any]:
    stand = await db.scalar(
        select(Stand).where(Stand.tenant_id == ctx.tenant, Stand.id == stand_id)
    )
    if stand is None:
        raise NotFound("That stand does not exist.")
    await _editable(db, ctx.tenant, stand.configuration_id)
    for field, value in payload.model_dump().items():
        setattr(stand, field, value)
    await db.flush()
    return {"id": str(stand.id)}


@router.delete("/stands/{stand_id}", status_code=204, summary="Remove a stand")
async def delete_stand(
    stand_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(VENUE_MANAGE))],
) -> None:
    stand = await db.scalar(
        select(Stand).where(Stand.tenant_id == ctx.tenant, Stand.id == stand_id)
    )
    if stand is None:
        raise NotFound("That stand does not exist.")
    await _editable(db, ctx.tenant, stand.configuration_id)
    await db.delete(stand)


@router.post("/stands/{stand_id}/sections", status_code=201, summary="Add a sector")
async def create_section(
    stand_id: UUID,
    payload: SectionIn,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(VENUE_MANAGE))],
) -> dict[str, Any]:
    stand = await db.scalar(
        select(Stand).where(Stand.tenant_id == ctx.tenant, Stand.id == stand_id)
    )
    if stand is None:
        raise NotFound("That stand does not exist.")
    await _editable(db, ctx.tenant, stand.configuration_id)

    section = Section(tenant_id=ctx.tenant, stand_id=stand_id, **payload.model_dump())
    db.add(section)
    await db.flush()
    return {"id": str(section.id)}


@router.patch("/sections/{section_id}", summary="Edit a sector")
async def update_section(
    section_id: UUID,
    payload: SectionIn,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(VENUE_MANAGE))],
) -> dict[str, Any]:
    section = await db.scalar(
        select(Section).where(Section.tenant_id == ctx.tenant, Section.id == section_id)
    )
    if section is None:
        raise NotFound("That sector does not exist.")
    for field, value in payload.model_dump().items():
        setattr(section, field, value)
    await db.flush()
    return {"id": str(section.id)}


@router.delete("/sections/{section_id}", status_code=204, summary="Remove a sector")
async def delete_section(
    section_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(VENUE_MANAGE))],
) -> None:
    section = await db.scalar(
        select(Section).where(Section.tenant_id == ctx.tenant, Section.id == section_id)
    )
    if section is None:
        raise NotFound("That sector does not exist.")
    await db.delete(section)


@router.post("/sections/{section_id}/seats", summary="Generate rows and seats")
async def generate_seats(
    section_id: UUID,
    payload: SeatPlanIn,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(VENUE_MANAGE))],
) -> dict[str, Any]:
    plan = venue_service.SeatPlan(
        row_count=payload.row_count,
        seats_per_row=payload.seats_per_row,
        row_start_label=payload.row_start_label,
        row_label_style=payload.row_label_style,
        first_seat_number=payload.first_seat_number,
        direction=payload.direction,
        aisle_after=tuple(payload.aisle_after),
        wheelchair_seats=tuple(payload.wheelchair_seats),
        companion_seats=tuple(payload.companion_seats),
        obstructed_seats=tuple(payload.obstructed_seats),
        blocked_seats=tuple(payload.blocked_seats),
    )
    created = await venue_service.generate_seats(
        db, ctx.tenant, section_id, plan, replace=payload.replace
    )
    return {"seats": created}


@router.get("/sections/{section_id}/seats", summary="Seats in a sector")
async def list_seats(
    section_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(VENUE_READ))],
) -> dict[str, Any]:
    rows = list(
        await db.scalars(
            select(SeatRow)
            .where(SeatRow.tenant_id == ctx.tenant, SeatRow.section_id == section_id)
            .order_by(SeatRow.display_order)
        )
    )
    out = []
    for row in rows:
        seats = await db.scalars(
            select(Seat)
            .where(Seat.tenant_id == ctx.tenant, Seat.row_id == row.id)
            .order_by(Seat.seat_index)
        )
        out.append(
            {
                "id": str(row.id),
                "label": row.label,
                "seats": [
                    {
                        "id": str(seat.id),
                        "label": seat.label,
                        "kind": seat.kind,
                        "blocked": seat.is_blocked,
                        "index": seat.seat_index,
                        "price_zone_id": str(seat.price_zone_id)
                        if seat.price_zone_id
                        else None,
                    }
                    for seat in seats
                ],
            }
        )
    return {"rows": out}


class SeatSelectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seat_ids: list[UUID] = Field(default_factory=list)
    section_ids: list[UUID] = Field(default_factory=list)
    price_zone_id: UUID | None = None
    blocked: bool | None = None


@router.post("/seats/assign", summary="Assign a price zone, or block seats")
async def assign_seats(
    payload: SeatSelectionIn,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(VENUE_MANAGE))],
) -> dict[str, Any]:
    """Bulk edit over a selection made on the map.

    One endpoint for both operations because the screen makes one selection
    and then chooses what to do with it, and two endpoints would mean the
    client sending the same list twice.
    """
    touched = 0
    if payload.price_zone_id is not None or payload.section_ids:
        touched += await venue_service.assign_price_zone(
            db,
            ctx.tenant,
            price_zone_id=payload.price_zone_id,
            section_ids=payload.section_ids or None,
            seat_ids=payload.seat_ids or None,
        )
    if payload.blocked is not None and payload.seat_ids:
        touched += await venue_service.set_seats_blocked(
            db, ctx.tenant, payload.seat_ids, blocked=payload.blocked
        )
    return {"updated": touched}


# --- price zones, access zones and gates ------------------------------------


@router.post(
    "/configurations/{configuration_id}/price-zones",
    status_code=201,
    summary="Add a price zone",
)
async def create_price_zone(
    configuration_id: UUID,
    payload: PriceZoneIn,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(VENUE_MANAGE))],
) -> dict[str, Any]:
    await _editable(db, ctx.tenant, configuration_id)
    zone = PriceZone(
        tenant_id=ctx.tenant, configuration_id=configuration_id, **payload.model_dump()
    )
    db.add(zone)
    await db.flush()
    return {"id": str(zone.id)}


@router.get("/configurations/{configuration_id}/price-zones", summary="Price zones")
async def list_price_zones(
    configuration_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(VENUE_READ))],
) -> list[dict[str, Any]]:
    zones = await db.scalars(
        select(PriceZone)
        .where(
            PriceZone.tenant_id == ctx.tenant,
            PriceZone.configuration_id == configuration_id,
        )
        .order_by(PriceZone.display_order)
    )
    return [
        {"id": str(z.id), "name": z.name, "code": z.code, "colour": z.colour} for z in zones
    ]


@router.post("/configurations/{configuration_id}/gates", status_code=201, summary="Add a gate")
async def create_gate(
    configuration_id: UUID,
    payload: GateIn,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(VENUE_MANAGE))],
) -> dict[str, Any]:
    await _editable(db, ctx.tenant, configuration_id)
    fields = payload.model_dump()
    section_ids = fields.pop("section_ids")

    gate = Gate(tenant_id=ctx.tenant, configuration_id=configuration_id, **fields)
    db.add(gate)
    await db.flush()

    for section_id in section_ids:
        db.add(GateSection(tenant_id=ctx.tenant, gate_id=gate.id, section_id=section_id))
    await db.flush()
    return {"id": str(gate.id)}


@router.put("/gates/{gate_id}", summary="Edit a gate and the sectors it serves")
async def update_gate(
    gate_id: UUID,
    payload: GateIn,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(VENUE_MANAGE))],
) -> dict[str, Any]:
    gate = await db.scalar(select(Gate).where(Gate.tenant_id == ctx.tenant, Gate.id == gate_id))
    if gate is None:
        raise NotFound("That gate does not exist.")
    await _editable(db, ctx.tenant, gate.configuration_id)

    fields = payload.model_dump()
    section_ids = fields.pop("section_ids")
    for field, value in fields.items():
        setattr(gate, field, value)

    await db.execute(
        delete(GateSection).where(
            GateSection.tenant_id == ctx.tenant, GateSection.gate_id == gate_id
        )
    )
    for section_id in section_ids:
        db.add(GateSection(tenant_id=ctx.tenant, gate_id=gate_id, section_id=section_id))
    await db.flush()
    return {"id": str(gate.id)}


@router.delete("/gates/{gate_id}", status_code=204, summary="Remove a gate")
async def delete_gate(
    gate_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(VENUE_MANAGE))],
) -> None:
    gate = await db.scalar(select(Gate).where(Gate.tenant_id == ctx.tenant, Gate.id == gate_id))
    if gate is None:
        raise NotFound("That gate does not exist.")
    await _editable(db, ctx.tenant, gate.configuration_id)
    await db.delete(gate)


@router.post(
    "/configurations/{configuration_id}/access-zones",
    status_code=201,
    summary="Add an access zone",
)
async def create_access_zone(
    configuration_id: UUID,
    payload: PriceZoneIn,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(VENUE_MANAGE))],
) -> dict[str, Any]:
    await _editable(db, ctx.tenant, configuration_id)
    zone = AccessZone(
        tenant_id=ctx.tenant,
        configuration_id=configuration_id,
        name=payload.name,
        code=payload.code,
    )
    db.add(zone)
    await db.flush()
    return {"id": str(zone.id)}


# --- ticket types -----------------------------------------------------------


@router.get("/ticket-types", summary="Ticket types")
async def list_ticket_types(
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(EVENT_READ))],
) -> list[dict[str, Any]]:
    types = await db.scalars(
        select(TicketType)
        .where(TicketType.tenant_id == ctx.tenant)
        .order_by(TicketType.display_order, TicketType.name)
    )
    return [
        {
            "id": str(t.id),
            "name": t.name,
            "code": t.code,
            "requires_proof": t.requires_proof,
            "is_complimentary": t.is_complimentary,
            "is_away": t.is_away,
            "is_active": t.is_active,
        }
        for t in types
    ]


@router.post("/ticket-types", status_code=201, summary="Add a ticket type")
async def create_ticket_type(
    payload: TicketTypeIn,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(PRICING_MANAGE))],
) -> dict[str, Any]:
    ticket_type = TicketType(tenant_id=ctx.tenant, **payload.model_dump())
    db.add(ticket_type)
    await db.flush()
    return {"id": str(ticket_type.id)}


# --- events -----------------------------------------------------------------


@router.get("/events", summary="Ticketed matches")
async def list_events(
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(EVENT_READ))],
    club_id: UUID | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    query = select(TicketedEvent).where(TicketedEvent.tenant_id == ctx.tenant)
    if club_id is not None:
        query = query.where(TicketedEvent.club_id == club_id)
    if status:
        query = query.where(TicketedEvent.status == status)

    events = list(await db.scalars(query.order_by(TicketedEvent.kickoff_at.desc())))
    return [
        {
            "id": str(e.id),
            "name": e.name,
            "slug": e.slug,
            "status": e.status,
            "category": e.category,
            "kickoff_at": e.kickoff_at.isoformat(),
            "doors_open_at": e.doors_open_at.isoformat() if e.doors_open_at else None,
            "sales_start_at": e.sales_start_at.isoformat() if e.sales_start_at else None,
            "sales_end_at": e.sales_end_at.isoformat() if e.sales_end_at else None,
            "is_public": e.is_public,
            "currency": e.currency,
            "venue_id": str(e.venue_id),
            "opponent_name": e.opponent_name,
            "competition_label": e.competition_label,
            "max_per_customer": e.max_per_customer,
            "avoid_orphan_seats": e.avoid_orphan_seats,
        }
        for e in events
    ]


@router.post("/events", status_code=201, summary="Create a match and freeze its stadium")
async def create_event(
    payload: EventIn,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(EVENT_MANAGE))],
) -> dict[str, Any]:
    fields = payload.model_dump()
    event = await event_service.create_event(
        db,
        ctx.tenant,
        club_id=fields.pop("club_id"),
        venue_id=fields.pop("venue_id"),
        configuration_id=fields.pop("configuration_id"),
        name=fields.pop("name"),
        slug=fields.pop("slug"),
        kickoff_at=fields.pop("kickoff_at"),
        **fields,
    )
    summary = await event_service.capacity_summary(db, ctx.tenant, event.id)
    return {"id": str(event.id), "capacity": summary}


@router.post("/events/{event_id}/publish", summary="Put a match on sale")
async def publish_event(
    event_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(EVENT_MANAGE))],
) -> dict[str, Any]:
    event = await event_service.publish_event(db, ctx.tenant, event_id)
    return {"id": str(event.id), "status": event.status}


@router.get("/events/{event_id}/capacity", summary="Inventory by state and stand")
async def event_capacity(
    event_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(EVENT_READ))],
) -> dict[str, Any]:
    return await event_service.capacity_summary(db, ctx.tenant, event_id)


@router.get("/events/{event_id}/layout", summary="The match's frozen stadium")
async def event_layout(
    event_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(EVENT_READ))],
) -> dict[str, Any]:
    snapshot = await event_service.get_snapshot(db, ctx.tenant, event_id)
    return {
        "source_version": snapshot.source_version,
        "source_name": snapshot.source_name,
        "total_capacity": snapshot.total_capacity,
        "payload": snapshot.payload,
        "availability": await inventory.availability_by_section(db, ctx.tenant, event_id),
    }


@router.get("/events/{event_id}/inventory", summary="Seats in one sector")
async def event_inventory(
    event_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(EVENT_READ))],
    section_id: UUID | None = None,
    limit: int = Query(default=2000, le=5000),
) -> list[dict[str, Any]]:
    query = select(EventSeatInventory).where(
        EventSeatInventory.tenant_id == ctx.tenant,
        EventSeatInventory.event_id == event_id,
    )
    if section_id is not None:
        query = query.where(EventSeatInventory.section_id == section_id)

    rows = await db.scalars(
        query.order_by(EventSeatInventory.row_label, EventSeatInventory.seat_index).limit(limit)
    )
    return [
        {
            "id": str(row.id),
            "seat_id": str(row.seat_id) if row.seat_id else None,
            "section_id": str(row.section_id),
            "stand": row.stand_name,
            "section": row.section_name,
            "row": row.row_label,
            "seat": row.seat_label,
            "kind": row.seat_kind,
            "index": row.seat_index,
            "state": row.state,
            "price_zone_code": row.price_zone_code,
        }
        for row in rows
    ]


# --- pricing ----------------------------------------------------------------


@router.get("/events/{event_id}/pricing", summary="The pricing matrix")
async def event_pricing(
    event_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(EVENT_READ))],
) -> dict[str, Any]:
    event = await event_service.get_event(db, ctx.tenant, event_id)
    zone_codes = [
        code
        for code in await db.scalars(
            select(EventSeatInventory.price_zone_code)
            .where(
                EventSeatInventory.tenant_id == ctx.tenant,
                EventSeatInventory.event_id == event_id,
            )
            .distinct()
        )
        if code
    ]
    return await pricing.matrix(db, ctx.tenant, event, zone_codes=sorted(zone_codes))


@router.put("/events/{event_id}/pricing", summary="Set this match's own prices")
async def set_event_pricing(
    event_id: UUID,
    payload: list[PriceRuleIn],
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(PRICING_MANAGE))],
) -> dict[str, Any]:
    """Replace the match-level overrides.

    Writes to an EVENT-scoped price list, leaving the season and ground lists
    alone — so clearing an override falls back to what the club already
    decided rather than to nothing.
    """
    event = await event_service.get_event(db, ctx.tenant, event_id)

    price_list = await db.scalar(
        select(PriceList).where(
            PriceList.tenant_id == ctx.tenant,
            PriceList.scope == "EVENT",
            PriceList.event_id == event_id,
        )
    )
    if price_list is None:
        price_list = PriceList(
            tenant_id=ctx.tenant,
            name=f"{event.name} overrides",
            scope="EVENT",
            event_id=event_id,
            currency=event.currency,
        )
        db.add(price_list)
        await db.flush()

    await db.execute(
        delete(PriceRule).where(
            PriceRule.tenant_id == ctx.tenant, PriceRule.price_list_id == price_list.id
        )
    )
    for rule in payload:
        db.add(
            PriceRule(tenant_id=ctx.tenant, price_list_id=price_list.id, **rule.model_dump())
        )
    await db.flush()
    return {"rules": len(payload)}


class VenuePriceListIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="Default prices", max_length=120)
    currency: str = Field(default="RON", min_length=3, max_length=3)
    rules: list[PriceRuleIn]


@router.put("/venues/{venue_id}/pricing", summary="The ground's default price list")
async def set_venue_pricing(
    venue_id: UUID,
    payload: VenuePriceListIn,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(PRICING_MANAGE))],
) -> dict[str, Any]:
    price_list = await db.scalar(
        select(PriceList).where(
            PriceList.tenant_id == ctx.tenant,
            PriceList.scope == "VENUE",
            PriceList.venue_id == venue_id,
        )
    )
    if price_list is None:
        price_list = PriceList(
            tenant_id=ctx.tenant,
            name=payload.name,
            scope="VENUE",
            venue_id=venue_id,
            currency=payload.currency,
        )
        db.add(price_list)
        await db.flush()

    await db.execute(
        delete(PriceRule).where(
            PriceRule.tenant_id == ctx.tenant, PriceRule.price_list_id == price_list.id
        )
    )
    for rule in payload.rules:
        db.add(
            PriceRule(tenant_id=ctx.tenant, price_list_id=price_list.id, **rule.model_dump())
        )
    await db.flush()
    return {"rules": len(payload.rules)}


# --- allocations and holds --------------------------------------------------


@router.get("/events/{event_id}/allocations", summary="Held and allocated inventory")
async def list_allocations(
    event_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(EVENT_READ))],
) -> list[dict[str, Any]]:
    rows = await db.scalars(
        select(Allocation)
        .where(Allocation.tenant_id == ctx.tenant, Allocation.event_id == event_id)
        .order_by(Allocation.created_at.desc())
    )
    return [
        {
            "id": str(a.id),
            "kind": a.kind,
            "reason": a.reason,
            "name": a.name,
            "owner_name": a.owner_name,
            "seat_count": a.seat_count,
            "expires_at": a.expires_at.isoformat() if a.expires_at else None,
            "released_at": a.released_at.isoformat() if a.released_at else None,
            "note": a.note,
        }
        for a in rows
    ]


@router.post("/events/{event_id}/allocations", status_code=201, summary="Hold seats back")
async def create_allocation(
    event_id: UUID,
    payload: AllocationIn,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(ALLOCATION_MANAGE))],
) -> dict[str, Any]:
    fields = payload.model_dump()
    inventory_ids = fields.pop("inventory_ids")
    section_id = fields.pop("section_id")

    if section_id is not None and not inventory_ids:
        # Closing a whole sector: take everything still free in it.
        inventory_ids = list(
            await db.scalars(
                select(EventSeatInventory.id).where(
                    EventSeatInventory.tenant_id == ctx.tenant,
                    EventSeatInventory.event_id == event_id,
                    EventSeatInventory.section_id == section_id,
                    EventSeatInventory.state.in_(("AVAILABLE", "REFUNDED_RELEASED")),
                )
            )
        )
    if not inventory_ids:
        raise ValidationFailed("No seats were selected.", field="inventory_ids")

    allocation = Allocation(
        tenant_id=ctx.tenant, event_id=event_id, seat_count=len(inventory_ids), **fields
    )
    db.add(allocation)
    await db.flush()

    state = "HARD_BLOCKED" if payload.kind == "HARD_HOLD" else "SOFT_ALLOCATED"
    moved = await inventory.set_state(
        db,
        ctx.tenant,
        event_id=event_id,
        inventory_ids=inventory_ids,
        state=state,
        allocation_id=allocation.id,
    )
    allocation.seat_count = moved
    await db.flush()
    return {"id": str(allocation.id), "seats": moved}


@router.post("/allocations/{allocation_id}/release", summary="Return seats to sale")
async def release_allocation(
    allocation_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(ALLOCATION_MANAGE))],
) -> dict[str, Any]:
    allocation = await db.scalar(
        select(Allocation).where(
            Allocation.tenant_id == ctx.tenant, Allocation.id == allocation_id
        )
    )
    if allocation is None:
        raise NotFound("That allocation does not exist.")

    released = await inventory.release_allocation(db, ctx.tenant, allocation_id=allocation_id)
    allocation.released_at = datetime.now(tz=allocation.created_at.tzinfo)
    await db.flush()
    return {"released": released}


# --- season tickets ---------------------------------------------------------


@router.get("/season-products", summary="Season tickets")
async def list_season_products(
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(EVENT_READ))],
    club_id: UUID | None = None,
) -> list[dict[str, Any]]:
    query = select(SeasonTicketProduct).where(SeasonTicketProduct.tenant_id == ctx.tenant)
    if club_id is not None:
        query = query.where(SeasonTicketProduct.club_id == club_id)

    rows = list(await db.scalars(query.order_by(SeasonTicketProduct.name)))
    out = []
    for product in rows:
        matches = await db.scalar(
            select(func.count())
            .select_from(SeasonTicketEvent)
            .where(
                SeasonTicketEvent.tenant_id == ctx.tenant,
                SeasonTicketEvent.product_id == product.id,
            )
        )
        sold = await db.scalar(
            select(func.count())
            .select_from(SeasonPass)
            .where(
                SeasonPass.tenant_id == ctx.tenant,
                SeasonPass.product_id == product.id,
                SeasonPass.status == "ACTIVE",
            )
        )
        out.append(
            {
                "id": str(product.id),
                "name": product.name,
                "status": product.status,
                "price_minor": product.price_minor,
                "currency": product.currency,
                "eligibility": product.eligibility,
                "is_transferable": product.is_transferable,
                "matches": int(matches or 0),
                "sold": int(sold or 0),
            }
        )
    return out


@router.post("/season-products", status_code=201, summary="Create a season ticket")
async def create_season_product(
    payload: SeasonProductIn,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(SEASON_MANAGE))],
) -> dict[str, Any]:
    fields = payload.model_dump()
    event_ids = fields.pop("event_ids")

    product = SeasonTicketProduct(tenant_id=ctx.tenant, **fields)
    db.add(product)
    await db.flush()

    for event_id in event_ids:
        db.add(
            SeasonTicketEvent(tenant_id=ctx.tenant, product_id=product.id, event_id=event_id)
        )
    await db.flush()
    return {"id": str(product.id), "matches": len(event_ids)}


@router.post("/season-products/{product_id}/open", summary="Put a season ticket on sale")
async def open_season_product(
    product_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(SEASON_MANAGE))],
) -> dict[str, Any]:
    product = await db.scalar(
        select(SeasonTicketProduct).where(
            SeasonTicketProduct.tenant_id == ctx.tenant,
            SeasonTicketProduct.id == product_id,
        )
    )
    if product is None:
        raise NotFound("That season ticket does not exist.")

    included = await db.scalar(
        select(func.count())
        .select_from(SeasonTicketEvent)
        .where(
            SeasonTicketEvent.tenant_id == ctx.tenant,
            SeasonTicketEvent.product_id == product_id,
        )
    )
    if not included:
        raise Conflict("Add at least one match before putting this on sale.")

    product.status = "ON_SALE"
    await db.flush()
    return {"id": str(product.id), "status": product.status}


@router.post(
    "/season-products/{product_id}/passes", status_code=201, summary="Sell a season ticket"
)
async def sell_season_pass(
    product_id: UUID,
    payload: SeasonPassIn,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(ORDER_MANAGE))],
) -> dict[str, Any]:
    season_pass = await issuing.issue_season_pass(
        db,
        ctx.tenant,
        product_id=product_id,
        seat_id=payload.seat_id,
        holder_name=payload.holder_name,
        holder_email=payload.holder_email,
    )
    return {
        "id": str(season_pass.id),
        "reference": season_pass.reference,
        "seat": f"{season_pass.row_label}{season_pass.seat_label}",
    }


# --- tickets and reporting --------------------------------------------------


@router.get("/events/{event_id}/tickets", summary="Tickets issued for a match")
async def list_tickets(
    event_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(ORDER_READ))],
    limit: int = Query(default=100, le=500),
) -> list[dict[str, Any]]:
    tickets = await db.scalars(
        select(Ticket)
        .where(Ticket.tenant_id == ctx.tenant, Ticket.event_id == event_id)
        .order_by(Ticket.created_at.desc())
        .limit(limit)
    )
    return [
        {
            "id": str(t.id),
            "ticket_number": t.ticket_number,
            "status": t.status,
            "ticket_type": t.ticket_type_name,
            "holder_name": t.holder_name,
            "price_minor": t.price_minor,
            "vat_minor": t.vat_minor,
            "fee_minor": t.fee_minor,
            "currency": t.currency,
            "issued_at": t.issued_at.isoformat() if t.issued_at else None,
        }
        for t in tickets
    ]


@router.get("/events/{event_id}/report", summary="Sales, occupancy and attendance")
async def event_report(
    event_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(REPORT_READ))],
) -> dict[str, Any]:
    """One request behind the whole match dashboard.

    Revenue is computed from the tickets, not from the orders: a ticket carries
    what was actually charged for that seat, and an order can hold a scarf as
    well.
    """
    from app.ticketing.access_service import live_counts

    capacity = await event_service.capacity_summary(db, ctx.tenant, event_id)
    scans = await live_counts(db, ctx.tenant, event_id)

    revenue = (
        await db.execute(
            select(
                func.coalesce(func.sum(Ticket.price_minor), 0),
                func.coalesce(func.sum(Ticket.vat_minor), 0),
                func.coalesce(func.sum(Ticket.fee_minor), 0),
                func.count(),
            ).where(
                Ticket.tenant_id == ctx.tenant,
                Ticket.event_id == event_id,
                Ticket.status == "ISSUED",
            )
        )
    ).one()
    gross, vat, fees, issued = revenue

    by_type = [
        {"ticket_type": name, "count": count, "gross_minor": int(total or 0)}
        for name, count, total in (
            await db.execute(
                select(
                    Ticket.ticket_type_name,
                    func.count(),
                    func.coalesce(func.sum(Ticket.price_minor), 0),
                )
                .where(
                    Ticket.tenant_id == ctx.tenant,
                    Ticket.event_id == event_id,
                    Ticket.status == "ISSUED",
                )
                .group_by(Ticket.ticket_type_name)
                .order_by(Ticket.ticket_type_name)
            )
        ).all()
    ]

    season_tickets = await db.scalar(
        select(func.count())
        .select_from(Ticket)
        .where(
            Ticket.tenant_id == ctx.tenant,
            Ticket.event_id == event_id,
            Ticket.season_pass_id.is_not(None),
        )
    )

    return {
        "capacity": capacity,
        "scans": scans,
        "tickets_issued": int(issued or 0),
        "season_tickets": int(season_tickets or 0),
        "revenue": {
            "gross_minor": int(gross or 0),
            "vat_minor": int(vat or 0),
            "fees_minor": int(fees or 0),
            "net_minor": int(gross or 0) - int(vat or 0),
        },
        "by_ticket_type": by_type,
    }
