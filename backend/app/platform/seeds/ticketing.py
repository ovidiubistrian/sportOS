"""Demonstration stadium and ticketing data.

Seeds a ground, a published layout, a fixture on sale, season tickets and a
handful of orders, so that every screen in the module has something real to
show on a fresh database.

**This is not a survey of Stadionul Mircea Chivu.** The stands, sectors, row
counts and gate positions are plausible demonstration data, not measurements. A
club going live replaces the whole configuration with its own; that is why the
layout is a versioned, forkable object rather than something baked into the
code.

Idempotent. Run it twice and the second run finds the venue already there and
stops, so it is safe in `init.sh` beside the other seeds.

    python -m app.platform.seeds.ticketing [club-slug]
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select

from app.core import model_registry  # noqa: F401
from app.core.db import platform_session, tenant_session
from app.ordering.models import Order, OrderLine
from app.ordering.service import new_reference
from app.tenants.models import Club
from app.ticketing import inventory, issuing
from app.ticketing.event_models import (
    Allocation,
    EventSeatInventory,
    PriceList,
    PriceRule,
    TicketType,
)
from app.ticketing.event_service import create_event, publish_event
from app.ticketing.ticket_models import SeasonTicketEvent, SeasonTicketProduct
from app.ticketing.venue_models import (
    AccessZone,
    Gate,
    GateSection,
    PriceZone,
    Section,
    Stand,
    Venue,
)
from app.ticketing.venue_service import SeatPlan, generate_seats, publish

log = structlog.get_logger(__name__)

DEFAULT_SLUG = "csm-resita"

# An abstract 1000x1000 drawing space with the pitch in the middle. The editor
# and the buyer-facing map both read these, so the shapes are data rather than
# anything the front end invents.
PITCH = {"x": 300, "y": 250, "width": 400, "height": 500}


def _box(x: int, y: int, width: int, height: int) -> dict[str, Any]:
    return {
        "points": [
            [x, y],
            [x + width, y],
            [x + width, y + height],
            [x, y + height],
        ]
    }


# Four stands, each split into sectors. Row and seat counts are kept modest so
# a fresh database seeds in seconds rather than minutes — the shape is what
# matters for a demonstration, not the exact capacity.
LAYOUT: list[dict[str, Any]] = [
    {
        "name": "Tribuna Principală",
        "code": "TP",
        "geometry": _box(120, 250, 170, 500),
        "sections": [
            {
                "name": "TP - VIP",
                "code": "TP-VIP",
                "zone": "VIP",
                "geometry": _box(130, 400, 150, 200),
                "rows": 6,
                "seats": 18,
                "start": "A",
            },
            {
                "name": "TP - Sector A",
                "code": "TP-A",
                "zone": "CAT1",
                "geometry": _box(130, 260, 150, 130),
                "rows": 10,
                "seats": 20,
                "start": "A",
            },
            {
                "name": "TP - Sector B",
                "code": "TP-B",
                "zone": "CAT1",
                "geometry": _box(130, 610, 150, 130),
                "rows": 10,
                "seats": 20,
                "start": "A",
                # The accessible bay: two wheelchair spaces and the companion
                # seats beside them, where the ramp comes out.
                "wheelchair": ["A:1", "A:3"],
                "companion": ["A:2", "A:4"],
            },
        ],
    },
    {
        "name": "Tribuna a II-a",
        "code": "T2",
        "geometry": _box(710, 250, 170, 500),
        "sections": [
            {
                "name": "T2 - Sector C",
                "code": "T2-C",
                "zone": "CAT2",
                "geometry": _box(720, 260, 150, 230),
                "rows": 12,
                "seats": 22,
                "start": "A",
            },
            {
                "name": "T2 - Sector D",
                "code": "T2-D",
                "zone": "CAT2",
                "geometry": _box(720, 510, 150, 230),
                "rows": 12,
                "seats": 22,
                "start": "A",
                # Behind the camera gantry: sold, but the club says so first.
                "obstructed": ["A:1", "A:2", "A:21", "A:22"],
            },
        ],
    },
    {
        "name": "Peluza Nord",
        "code": "PN",
        "geometry": _box(300, 90, 400, 150),
        "sections": [
            {
                "name": "Peluza Nord",
                "code": "PN-GA",
                "zone": "CAT2",
                "geometry": _box(310, 100, 380, 130),
                "general_admission": 600,
            },
        ],
    },
    {
        "name": "Peluza Sud",
        "code": "PS",
        "geometry": _box(300, 760, 400, 150),
        "sections": [
            {
                "name": "Peluza Sud",
                "code": "PS-GA",
                "zone": "CAT2",
                "geometry": _box(310, 770, 250, 130),
                "general_admission": 400,
            },
            {
                "name": "Sector Oaspeți",
                "code": "PS-AWAY",
                "zone": "AWAY",
                "geometry": _box(580, 770, 110, 130),
                "general_admission": 200,
            },
        ],
    },
]

ZONES = [
    {"name": "Categoria 1", "code": "CAT1", "colour": "#1d4ed8", "order": 1},
    {"name": "Categoria 2", "code": "CAT2", "colour": "#0f766e", "order": 2},
    {"name": "VIP", "code": "VIP", "colour": "#b45309", "order": 0},
    {"name": "Oaspeți", "code": "AWAY", "colour": "#be123c", "order": 3},
    {"name": "Accesibil", "code": "ACCESS", "colour": "#7c3aed", "order": 4},
]

GATES = [
    {
        "name": "Poarta A - Tribuna Principală",
        "code": "A",
        "kind": "PUBLIC",
        "zone": "VEST",
        "sections": ["TP-A", "TP-B"],
        "accessible": True,
    },
    {
        "name": "Poarta B - VIP și presă",
        "code": "B",
        "kind": "VIP",
        "zone": "VEST",
        "sections": ["TP-VIP"],
    },
    {
        "name": "Poarta C - Tribuna a II-a",
        "code": "C",
        "kind": "PUBLIC",
        "zone": "EST",
        "sections": ["T2-C", "T2-D"],
    },
    {
        "name": "Poarta D - Peluze",
        "code": "D",
        "kind": "PUBLIC",
        "zone": "PELUZE",
        "sections": ["PN-GA", "PS-GA"],
    },
    {
        "name": "Poarta E - Oaspeți",
        "code": "E",
        "kind": "AWAY",
        "zone": "OASPETI",
        "sections": ["PS-AWAY"],
        "side": "AWAY",
    },
]

TICKET_TYPES = [
    {"name": "Adult", "code": "ADULT", "order": 0},
    {"name": "Copil", "code": "CHILD", "order": 1, "proof": True},
    {"name": "Pensionar", "code": "SENIOR", "order": 2, "proof": True},
    {"name": "Student", "code": "STUDENT", "order": 3, "proof": True},
    {"name": "VIP", "code": "VIP", "order": 4},
    {"name": "Protocol", "code": "COMP", "order": 5, "complimentary": True},
    {"name": "Suporter oaspete", "code": "AWAY", "order": 6, "away": True},
]

# Zone x type, in bani. Adult first; concessions are a share of it.
PRICES: dict[str, dict[str, int]] = {
    "VIP": {"ADULT": 15000, "CHILD": 15000, "SENIOR": 15000, "STUDENT": 15000, "VIP": 15000},
    "CAT1": {"ADULT": 5000, "CHILD": 2500, "SENIOR": 2500, "STUDENT": 3000, "VIP": 5000},
    "CAT2": {"ADULT": 3000, "CHILD": 1500, "SENIOR": 1500, "STUDENT": 2000, "VIP": 3000},
    "AWAY": {"ADULT": 3000, "AWAY": 3000},
    "ACCESS": {"ADULT": 1500, "CHILD": 0, "SENIOR": 1500, "STUDENT": 1500},
}

VAT_RATE_BP = 1900


async def _resolve_club(slug: str) -> tuple[UUID, UUID, str] | None:
    async with platform_session(
        reason="seed: resolve the club to attach demonstration ticketing to",
        routine=True,
    ) as session:
        club = await session.scalar(select(Club).where(Club.slug == slug))
        if club is None:
            return None
        return club.tenant_id, club.id, club.display_name


async def seed_ticketing(tenant_id: UUID, club_id: UUID, club_name: str) -> dict[str, Any]:
    """Everything a demonstration needs, in one transaction."""
    async with tenant_session(tenant_id) as session:
        existing = await session.scalar(
            select(Venue).where(Venue.tenant_id == tenant_id, Venue.code == "MCHIVU")
        )
        if existing is not None:
            log.info("ticketing_seed_skipped", reason="venue already exists")
            return {"skipped": True}

        venue = Venue(
            tenant_id=tenant_id,
            club_id=club_id,
            name="Stadionul Mircea Chivu",
            code="MCHIVU",
            address="Strada Făgărașului 1",
            city="Reșița",
            country_code="RO",
            timezone="Europe/Bucharest",
            currency="RON",
            pitch_orientation="NORTH_SOUTH",
        )
        session.add(venue)
        await session.flush()

        from app.ticketing.venue_models import VenueConfiguration

        config = VenueConfiguration(
            tenant_id=tenant_id,
            venue_id=venue.id,
            # Named so nobody mistakes it for a survey of the real ground.
            name="Fotbal - configurație demonstrativă",
            version=1,
            status="DRAFT",
        )
        session.add(config)
        await session.flush()

        zones: dict[str, PriceZone] = {}
        for spec in ZONES:
            zone = PriceZone(
                tenant_id=tenant_id,
                configuration_id=config.id,
                name=spec["name"],
                code=spec["code"],
                colour=spec["colour"],
                display_order=spec["order"],
            )
            session.add(zone)
            zones[spec["code"]] = zone
        await session.flush()

        access_zones: dict[str, AccessZone] = {}
        for code, name in (
            ("VEST", "Concourse vest"),
            ("EST", "Concourse est"),
            ("PELUZE", "Peluze"),
            ("OASPETI", "Zonă oaspeți"),
        ):
            zone = AccessZone(
                tenant_id=tenant_id, configuration_id=config.id, name=name, code=code
            )
            session.add(zone)
            access_zones[code] = zone
        await session.flush()

        sections: dict[str, Section] = {}
        for order, stand_spec in enumerate(LAYOUT):
            stand = Stand(
                tenant_id=tenant_id,
                configuration_id=config.id,
                name=stand_spec["name"],
                code=stand_spec["code"],
                display_order=order,
                geometry=stand_spec["geometry"],
            )
            session.add(stand)
            await session.flush()

            for index, spec in enumerate(stand_spec["sections"]):
                is_ga = "general_admission" in spec
                section = Section(
                    tenant_id=tenant_id,
                    stand_id=stand.id,
                    price_zone_id=zones[spec["zone"]].id,
                    name=spec["name"],
                    code=spec["code"],
                    kind="GENERAL_ADMISSION" if is_ga else "RESERVED",
                    declared_capacity=spec.get("general_admission", 0),
                    display_order=index,
                    geometry=spec["geometry"],
                )
                session.add(section)
                await session.flush()
                sections[spec["code"]] = section

                if not is_ga:
                    await generate_seats(
                        session,
                        tenant_id,
                        section.id,
                        SeatPlan(
                            row_count=spec["rows"],
                            seats_per_row=spec["seats"],
                            row_start_label=spec.get("start", "A"),
                            wheelchair_seats=tuple(spec.get("wheelchair", ())),
                            companion_seats=tuple(spec.get("companion", ())),
                            obstructed_seats=tuple(spec.get("obstructed", ())),
                        ),
                    )

        for spec in GATES:
            gate = Gate(
                tenant_id=tenant_id,
                configuration_id=config.id,
                access_zone_id=access_zones[spec["zone"]].id,
                name=spec["name"],
                code=spec["code"],
                kind=spec["kind"],
                supporter_side=spec.get("side", "ANY"),
                is_accessible=spec.get("accessible", False),
            )
            session.add(gate)
            await session.flush()
            for code in spec["sections"]:
                session.add(
                    GateSection(
                        tenant_id=tenant_id, gate_id=gate.id, section_id=sections[code].id
                    )
                )
        await session.flush()

        await publish(session, tenant_id, config.id)
        await session.refresh(config)

        types: dict[str, TicketType] = {}
        for spec in TICKET_TYPES:
            ticket_type = TicketType(
                tenant_id=tenant_id,
                name=spec["name"],
                code=spec["code"],
                requires_proof=spec.get("proof", False),
                is_complimentary=spec.get("complimentary", False),
                is_away=spec.get("away", False),
                display_order=spec["order"],
            )
            session.add(ticket_type)
            types[spec["code"]] = ticket_type
        await session.flush()

        price_list = PriceList(
            tenant_id=tenant_id,
            name="Prețuri implicite - Mircea Chivu",
            scope="VENUE",
            venue_id=venue.id,
            currency="RON",
        )
        session.add(price_list)
        await session.flush()

        for zone_code, by_type in PRICES.items():
            for type_code, amount in by_type.items():
                session.add(
                    PriceRule(
                        tenant_id=tenant_id,
                        price_list_id=price_list.id,
                        ticket_type_id=types[type_code].id,
                        price_zone_code=zone_code,
                        amount_minor=amount,
                        vat_rate_bp=VAT_RATE_BP,
                        vat_included=True,
                    )
                )
        # Protocol tickets are free everywhere, and saying so explicitly beats
        # letting the resolver refuse them for want of a rule.
        for zone_code in PRICES:
            session.add(
                PriceRule(
                    tenant_id=tenant_id,
                    price_list_id=price_list.id,
                    ticket_type_id=types["COMP"].id,
                    price_zone_code=zone_code,
                    amount_minor=0,
                    vat_rate_bp=0,
                )
            )
        await session.flush()

        kickoff = (datetime.now(UTC) + timedelta(days=12)).replace(
            hour=16, minute=0, second=0, microsecond=0
        )
        events = []
        for index, opponent in enumerate(
            ("Politehnica Timișoara", "CSM Slatina", "Unirea Alba Iulia")
        ):
            event = await create_event(
                session,
                tenant_id,
                club_id=club_id,
                venue_id=venue.id,
                configuration_id=config.id,
                name=f"{club_name} - {opponent}",
                slug=f"csm-{opponent.split()[0].lower()}-{index + 1}",
                kickoff_at=kickoff + timedelta(days=14 * index),
                doors_open_at=kickoff + timedelta(days=14 * index) - timedelta(hours=2),
                opponent_name=opponent,
                competition_label="Liga 2",
                category="A" if index == 0 else "B",
                sales_start_at=datetime.now(UTC) - timedelta(days=1),
                sales_end_at=kickoff + timedelta(days=14 * index),
                max_per_customer=8,
            )
            await publish_event(session, tenant_id, event.id)
            events.append(event)

        first = events[0]

        # The camera platform, and the away allocation the club can hand back.
        camera = Allocation(
            tenant_id=tenant_id,
            event_id=first.id,
            kind="HARD_HOLD",
            reason="CAMERA_PLATFORM",
            name="Platformă camere TV",
            note="Rândul A din sectorul D, ocupat de platforma de filmare.",
        )
        session.add(camera)
        await session.flush()

        camera_seats = list(
            await session.scalars(
                select(EventSeatInventory.id).where(
                    EventSeatInventory.tenant_id == tenant_id,
                    EventSeatInventory.event_id == first.id,
                    EventSeatInventory.section_code == "T2-D",
                    EventSeatInventory.row_label == "A",
                )
            )
        )
        if camera_seats:
            await inventory.set_state(
                session,
                tenant_id,
                event_id=first.id,
                inventory_ids=camera_seats,
                state="HARD_BLOCKED",
                allocation_id=camera.id,
            )
            camera.seat_count = len(camera_seats)

        away = Allocation(
            tenant_id=tenant_id,
            event_id=first.id,
            kind="SOFT_ALLOCATION",
            reason="AWAY_SUPPORTERS",
            name="Alocare suporteri oaspeți",
            owner_name="Politehnica Timișoara",
            access_code="OASPETI2026",
            expires_at=first.kickoff_at - timedelta(days=3),
            note="Se eliberează spre vânzare publică dacă nu sunt revendicate.",
        )
        session.add(away)
        await session.flush()

        away_seats = list(
            await session.scalars(
                select(EventSeatInventory.id)
                .where(
                    EventSeatInventory.tenant_id == tenant_id,
                    EventSeatInventory.event_id == first.id,
                    EventSeatInventory.section_code == "PS-AWAY",
                    EventSeatInventory.state == "AVAILABLE",
                )
                .limit(150)
            )
        )
        if away_seats:
            await inventory.set_state(
                session,
                tenant_id,
                event_id=first.id,
                inventory_ids=away_seats,
                state="SOFT_ALLOCATED",
                allocation_id=away.id,
            )
            away.seat_count = len(away_seats)
        await session.flush()

        season = SeasonTicketProduct(
            tenant_id=tenant_id,
            club_id=club_id,
            configuration_id=config.id,
            name="Abonament 2026/27 - Tribuna Principală",
            description="Toate meciurile de acasă din sezon, același loc.",
            price_minor=45000,
            currency="RON",
            status="ON_SALE",
            eligibility="PUBLIC",
            sales_start_at=datetime.now(UTC) - timedelta(days=7),
            is_transferable=True,
        )
        session.add(season)
        await session.flush()
        for event in events:
            session.add(
                SeasonTicketEvent(tenant_id=tenant_id, product_id=season.id, event_id=event.id)
            )
        await session.flush()

        orders = await _seed_orders(session, tenant_id, club_id, first)
        passes = await _seed_season_passes(session, tenant_id, season.id, first.id)

        log.info(
            "ticketing_seeded",
            venue=venue.name,
            capacity=config.total_capacity,
            events=len(events),
            orders=orders,
            season_passes=passes,
        )
        return {
            "venue_id": str(venue.id),
            "configuration_id": str(config.id),
            "capacity": config.total_capacity,
            "events": [str(e.id) for e in events],
            "orders": orders,
            "season_passes": passes,
        }


async def _seed_orders(session, tenant_id: UUID, club_id: UUID, event) -> int:
    """A handful of real sales, so the reports have something in them."""
    buyers = [
        ("Andrei Popescu", "andrei.popescu@example.ro", "TP-A", "ADULT", 2),
        ("Maria Ionescu", "maria.ionescu@example.ro", "TP-B", "SENIOR", 1),
        ("Vlad Georgescu", "vlad.georgescu@example.ro", "T2-C", "ADULT", 3),
        ("Elena Dumitru", "elena.dumitru@example.ro", "PN-GA", "CHILD", 2),
    ]

    placed = 0
    for name, email, section_code, type_code, quantity in buyers:
        seats = list(
            await session.scalars(
                select(EventSeatInventory)
                .where(
                    EventSeatInventory.tenant_id == tenant_id,
                    EventSeatInventory.event_id == event.id,
                    EventSeatInventory.section_code == section_code,
                    EventSeatInventory.state == "AVAILABLE",
                )
                .order_by(EventSeatInventory.row_label, EventSeatInventory.seat_index)
                .limit(quantity)
            )
        )
        if len(seats) < quantity:
            continue

        order = Order(
            tenant_id=tenant_id,
            club_id=club_id,
            reference=new_reference(),
            status="AWAITING_COLLECTION",
            currency="RON",
            buyer_name=name,
            buyer_email=email,
            payment_method="ON_COLLECTION",
            placed_at=datetime.now(UTC),
        )
        session.add(order)
        await session.flush()

        for seat in seats:
            seat.state = "SOLD"
            seat.order_id = order.id
            seat.ticket_type_code = type_code
        await session.flush()

        tickets = await issuing.issue_for_order(
            session, tenant_id, order_id=order.id, holder_name=name
        )
        total = sum(t.price_minor + t.fee_minor for t in tickets)
        order.subtotal_minor = total
        order.total_minor = total

        for seat, ticket in zip(seats, tickets, strict=False):
            session.add(
                OrderLine(
                    tenant_id=tenant_id,
                    order_id=order.id,
                    line_type="TICKET",
                    reference_id=seat.id,
                    description=f"{event.name} - {seat.section_name}",
                    unit_price_minor=ticket.price_minor,
                    quantity=1,
                    total_minor=ticket.price_minor,
                )
            )
        await session.flush()
        placed += 1

    return placed


async def _seed_season_passes(
    session, tenant_id: UUID, product_id: UUID, event_id: UUID
) -> int:
    """Two season tickets, so the per-match entitlement rule is visible."""
    from app.ticketing.venue_models import Seat

    holders = [("Ion Marin", "ion.marin@example.ro"), ("Ana Petrescu", None)]
    sold = 0

    for holder, email in holders:
        seat_row = await session.scalar(
            select(EventSeatInventory)
            .where(
                EventSeatInventory.tenant_id == tenant_id,
                EventSeatInventory.event_id == event_id,
                EventSeatInventory.section_code == "TP-VIP",
                EventSeatInventory.state == "AVAILABLE",
                EventSeatInventory.seat_id.is_not(None),
            )
            .order_by(EventSeatInventory.row_label, EventSeatInventory.seat_index)
        )
        if seat_row is None:
            break

        seat = await session.scalar(
            select(Seat).where(Seat.tenant_id == tenant_id, Seat.id == seat_row.seat_id)
        )
        if seat is None:
            break

        await issuing.issue_season_pass(
            session,
            tenant_id,
            product_id=product_id,
            seat_id=seat.id,
            holder_name=holder,
            holder_email=email,
        )
        sold += 1

    return sold


async def main() -> None:
    slug = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SLUG
    resolved = await _resolve_club(slug)
    if resolved is None:
        log.error("ticketing_seed_no_club", slug=slug)
        raise SystemExit(f"No club with slug {slug!r}. Seed the demo tenants first.")

    tenant_id, club_id, club_name = resolved
    await seed_ticketing(tenant_id, club_id, club_name)


if __name__ == "__main__":
    asyncio.run(main())
