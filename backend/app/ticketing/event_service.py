"""Creating a ticketed event: freezing the stadium and minting the inventory.

This module is where the architecture's central rule is actually executed. On
creation an event does two things, once, in one transaction:

1. serialises the whole venue configuration into an
   `EventConfigurationSnapshot`, and
2. mints one `EventSeatInventory` row for every admission it describes.

After that the event never reads the master configuration again. Not to draw
the map, not to price, not to validate a scan. Everything it needs it owns.

The consequence is the acceptance criterion "editing the venue master does not
change the published match", and it holds by construction rather than by
discipline: there is no code path from an event to a `stand`, `section` or
`seat` row, so no later edit can reach it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.ticketing.event_models import (
    EventConfigurationSnapshot,
    EventSeatInventory,
    TicketedEvent,
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

# A stadium of 30 000 seats is 30 000 inventory rows, which is fine. A typo of
# 30 000 000 is not, and would take the database down rather than fail. The
# ceiling is deliberately far above any real ground.
MAX_INVENTORY_ROWS = 200_000


async def build_snapshot_payload(
    session: AsyncSession, tenant_id: UUID, configuration_id: UUID
) -> dict[str, Any]:
    """Serialise a configuration whole: stands, sectors, rows, seats, gates.

    Read once here and never again. It is verbose on purpose — the buyer-facing
    map, the admin map and the scanner manifest are all drawn from this, and a
    snapshot that needed a join back to the master to be useful would not be a
    snapshot.
    """
    config = await session.scalar(
        select(VenueConfiguration).where(
            VenueConfiguration.tenant_id == tenant_id,
            VenueConfiguration.id == configuration_id,
        )
    )
    if config is None:
        raise NotFound("That stadium configuration does not exist.")

    venue = await session.scalar(
        select(Venue).where(Venue.tenant_id == tenant_id, Venue.id == config.venue_id)
    )

    zones = {
        zone.id: {
            "id": str(zone.id),
            "name": zone.name,
            "code": zone.code,
            "colour": zone.colour,
            "display_order": zone.display_order,
        }
        for zone in await session.scalars(
            select(PriceZone)
            .where(PriceZone.tenant_id == tenant_id, PriceZone.configuration_id == config.id)
            .order_by(PriceZone.display_order)
        )
    }

    stands: list[dict[str, Any]] = []
    for stand in await session.scalars(
        select(Stand)
        .where(Stand.tenant_id == tenant_id, Stand.configuration_id == config.id)
        .order_by(Stand.display_order)
    ):
        sections: list[dict[str, Any]] = []
        for section in await session.scalars(
            select(Section)
            .where(Section.tenant_id == tenant_id, Section.stand_id == stand.id)
            .order_by(Section.display_order)
        ):
            zone = zones.get(section.price_zone_id) if section.price_zone_id else None
            rows: list[dict[str, Any]] = []
            if section.kind == "RESERVED":
                for row in await session.scalars(
                    select(SeatRow)
                    .where(SeatRow.tenant_id == tenant_id, SeatRow.section_id == section.id)
                    .order_by(SeatRow.display_order)
                ):
                    seats = [
                        {
                            "id": str(seat.id),
                            "label": seat.label,
                            "kind": seat.kind,
                            "blocked": seat.is_blocked,
                            "index": seat.seat_index,
                            "zone": (zones.get(seat.price_zone_id) or {}).get("code")
                            if seat.price_zone_id
                            else (zone or {}).get("code"),
                        }
                        for seat in await session.scalars(
                            select(Seat)
                            .where(Seat.tenant_id == tenant_id, Seat.row_id == row.id)
                            .order_by(Seat.seat_index)
                        )
                    ]
                    rows.append({"id": str(row.id), "label": row.label, "seats": seats})

            sections.append(
                {
                    "id": str(section.id),
                    "name": section.name,
                    "code": section.code,
                    "kind": section.kind,
                    "capacity": section.declared_capacity,
                    "geometry": section.geometry or {},
                    "price_zone": zone,
                    "rows": rows,
                }
            )

        stands.append(
            {
                "id": str(stand.id),
                "name": stand.name,
                "code": stand.code,
                "geometry": stand.geometry or {},
                "sections": sections,
            }
        )

    access_zones = {
        zone.id: {"id": str(zone.id), "name": zone.name, "code": zone.code}
        for zone in await session.scalars(
            select(AccessZone).where(
                AccessZone.tenant_id == tenant_id, AccessZone.configuration_id == config.id
            )
        )
    }

    gates: list[dict[str, Any]] = []
    for gate in await session.scalars(
        select(Gate).where(Gate.tenant_id == tenant_id, Gate.configuration_id == config.id)
    ):
        served = list(
            await session.scalars(
                select(GateSection.section_id).where(
                    GateSection.tenant_id == tenant_id, GateSection.gate_id == gate.id
                )
            )
        )
        gates.append(
            {
                "id": str(gate.id),
                "name": gate.name,
                "code": gate.code,
                "kind": gate.kind,
                "supporter_side": gate.supporter_side,
                "is_accessible": gate.is_accessible,
                "access_zone": access_zones.get(gate.access_zone_id)
                if gate.access_zone_id
                else None,
                "section_ids": [str(s) for s in served],
            }
        )

    return {
        "venue": {
            "id": str(venue.id) if venue else None,
            "name": venue.name if venue else "",
            "city": venue.city if venue else None,
            "timezone": venue.timezone if venue else "Europe/Bucharest",
            "pitch_orientation": venue.pitch_orientation if venue else "NORTH_SOUTH",
        },
        "configuration": {
            "id": str(config.id),
            "name": config.name,
            "version": config.version,
        },
        "price_zones": list(zones.values()),
        "access_zones": list(access_zones.values()),
        "stands": stands,
        "gates": gates,
    }


async def snapshot_and_build_inventory(
    session: AsyncSession, tenant_id: UUID, event: TicketedEvent
) -> EventConfigurationSnapshot:
    """Freeze the layout and create every sellable row. Once per event.

    Raises if a snapshot already exists — re-snapshotting is precisely the
    mutation the design forbids, and a caller trying it has a bug that would
    otherwise silently move somebody's seat.
    """
    existing = await session.scalar(
        select(EventConfigurationSnapshot).where(
            EventConfigurationSnapshot.tenant_id == tenant_id,
            EventConfigurationSnapshot.event_id == event.id,
        )
    )
    if existing is not None:
        raise Conflict(
            "This event already has a stadium snapshot and cannot be "
            "re-created from the master.",
            event_id=str(event.id),
        )

    config = await session.scalar(
        select(VenueConfiguration).where(
            VenueConfiguration.tenant_id == tenant_id,
            VenueConfiguration.id == event.configuration_id,
        )
    )
    if config is None:
        raise NotFound("That stadium configuration does not exist.")
    if config.status != "PUBLISHED":
        raise ValidationFailed(
            "A match can only be created from a published stadium configuration.",
            field="configuration_id",
        )

    payload = await build_snapshot_payload(session, tenant_id, config.id)

    rows: list[EventSeatInventory] = []
    for stand in payload["stands"]:
        for section in stand["sections"]:
            zone_code = (section.get("price_zone") or {}).get("code")
            section_id = UUID(section["id"])

            if section["kind"] == "GENERAL_ADMISSION":
                # One row per standing place. Uniform with reserved seating, so
                # a GA admission can be blocked, allocated and refunded exactly
                # like a seated one — see the note in `EventSeatInventory`.
                for index in range(int(section["capacity"] or 0)):
                    rows.append(
                        EventSeatInventory(
                            tenant_id=tenant_id,
                            event_id=event.id,
                            seat_id=None,
                            section_id=section_id,
                            stand_name=stand["name"],
                            section_name=section["name"],
                            section_code=section["code"],
                            section_kind=section["kind"],
                            price_zone_code=zone_code,
                            seat_index=index,
                            state="AVAILABLE",
                        )
                    )
                continue

            for row in section["rows"]:
                for seat in row["seats"]:
                    rows.append(
                        EventSeatInventory(
                            tenant_id=tenant_id,
                            event_id=event.id,
                            seat_id=UUID(seat["id"]),
                            section_id=section_id,
                            stand_name=stand["name"],
                            section_name=section["name"],
                            section_code=section["code"],
                            section_kind=section["kind"],
                            row_label=row["label"],
                            seat_label=seat["label"],
                            seat_kind=seat["kind"],
                            seat_index=seat["index"],
                            price_zone_code=seat.get("zone") or zone_code,
                            # A seat blocked in the master starts the match
                            # blocked. It is a broken seat, not an unsold one,
                            # and the capacity report must say so.
                            state="HARD_BLOCKED" if seat["blocked"] else "AVAILABLE",
                        )
                    )

    if not rows:
        raise ValidationFailed(
            "That stadium configuration has nothing to sell.", field="configuration_id"
        )
    if len(rows) > MAX_INVENTORY_ROWS:
        raise ValidationFailed(
            f"That configuration would create {len(rows)} places, which is beyond "
            f"the {MAX_INVENTORY_ROWS} this platform allows for one match.",
            field="configuration_id",
        )

    session.add_all(rows)

    sellable = sum(1 for row in rows if row.state == "AVAILABLE")
    snapshot = EventConfigurationSnapshot(
        tenant_id=tenant_id,
        event_id=event.id,
        source_configuration_id=config.id,
        source_version=config.version,
        source_name=config.name,
        payload=payload,
        total_capacity=sellable,
    )
    session.add(snapshot)
    await session.flush()
    return snapshot


async def create_event(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    club_id: UUID,
    venue_id: UUID,
    configuration_id: UUID,
    name: str,
    slug: str,
    kickoff_at: datetime,
    **fields: Any,
) -> TicketedEvent:
    """Create a match and freeze its stadium in the same transaction.

    Deliberately not two steps. An event that exists without inventory is one
    a club can put on sale by accident, and the window between the two calls is
    exactly when that happens.
    """
    config = await session.scalar(
        select(VenueConfiguration).where(
            VenueConfiguration.tenant_id == tenant_id,
            VenueConfiguration.id == configuration_id,
        )
    )
    if config is None:
        raise NotFound("That stadium configuration does not exist.")
    if config.venue_id != venue_id:
        raise ValidationFailed(
            "That configuration belongs to a different ground.", field="configuration_id"
        )

    event = TicketedEvent(
        tenant_id=tenant_id,
        club_id=club_id,
        venue_id=venue_id,
        configuration_id=configuration_id,
        name=name,
        slug=slug,
        kickoff_at=kickoff_at,
        status="DRAFT",
        **fields,
    )
    session.add(event)
    await session.flush()

    await snapshot_and_build_inventory(session, tenant_id, event)
    return event


async def publish_event(
    session: AsyncSession, tenant_id: UUID, event_id: UUID
) -> TicketedEvent:
    """Put a match on sale.

    Refuses an event with no price for anything sellable — a published match
    whose seats cannot be priced shows a supporter an empty map and a support
    ticket for the club.
    """
    event = await get_event(session, tenant_id, event_id)
    if event.status == "CANCELLED":
        raise Conflict("A cancelled match cannot be published.")

    from app.ticketing.pricing import priced_zone_codes  # circular at module level

    sellable = list(
        await session.scalars(
            select(EventSeatInventory.price_zone_code)
            .where(
                EventSeatInventory.tenant_id == tenant_id,
                EventSeatInventory.event_id == event_id,
                EventSeatInventory.state == "AVAILABLE",
            )
            .distinct()
        )
    )
    if not sellable:
        raise ValidationFailed("This match has nothing available to sell.")

    priced = await priced_zone_codes(session, tenant_id, event)
    unpriced = {code for code in sellable if code not in priced}
    if unpriced:
        raise ValidationFailed(
            "Some parts of the ground have no price for this match.",
            field="pricing",
            zones=sorted(code or "(none)" for code in unpriced),
        )

    event.status = "PUBLISHED"
    event.published_at = datetime.now(UTC)
    await session.flush()
    return event


async def get_event(session: AsyncSession, tenant_id: UUID, event_id: UUID) -> TicketedEvent:
    event = await session.scalar(
        select(TicketedEvent).where(
            TicketedEvent.tenant_id == tenant_id, TicketedEvent.id == event_id
        )
    )
    if event is None:
        raise NotFound("That match does not exist.")
    return event


async def get_snapshot(
    session: AsyncSession, tenant_id: UUID, event_id: UUID
) -> EventConfigurationSnapshot:
    snapshot = await session.scalar(
        select(EventConfigurationSnapshot).where(
            EventConfigurationSnapshot.tenant_id == tenant_id,
            EventConfigurationSnapshot.event_id == event_id,
        )
    )
    if snapshot is None:
        raise NotFound("That match has no stadium snapshot.")
    return snapshot


async def capacity_summary(
    session: AsyncSession, tenant_id: UUID, event_id: UUID
) -> dict[str, Any]:
    """Inventory counted by state, and by stand — what the dashboard shows."""
    by_state = dict(
        (
            await session.execute(
                select(EventSeatInventory.state, func.count())
                .where(
                    EventSeatInventory.tenant_id == tenant_id,
                    EventSeatInventory.event_id == event_id,
                )
                .group_by(EventSeatInventory.state)
            )
        ).all()
    )

    by_stand = [
        {"stand": stand, "total": total, "sold": sold}
        for stand, total, sold in (
            await session.execute(
                select(
                    EventSeatInventory.stand_name,
                    func.count(),
                    func.count().filter(
                        EventSeatInventory.state.in_(("SOLD", "COMPLIMENTARY"))
                    ),
                )
                .where(
                    EventSeatInventory.tenant_id == tenant_id,
                    EventSeatInventory.event_id == event_id,
                )
                .group_by(EventSeatInventory.stand_name)
                .order_by(EventSeatInventory.stand_name)
            )
        ).all()
    ]

    total = sum(by_state.values())
    sold = by_state.get("SOLD", 0) + by_state.get("COMPLIMENTARY", 0)
    blocked = by_state.get("HARD_BLOCKED", 0)
    sellable = total - blocked

    return {
        "total": total,
        "sellable": sellable,
        "sold": sold,
        "available": by_state.get("AVAILABLE", 0) + by_state.get("REFUNDED_RELEASED", 0),
        "held": by_state.get("CART_HELD", 0),
        "reserved": by_state.get("RESERVED", 0),
        "blocked": blocked,
        "allocated": by_state.get("SOFT_ALLOCATED", 0),
        "complimentary": by_state.get("COMPLIMENTARY", 0),
        # Occupancy against what can actually be sold, not against the
        # architectural capacity — a club that closes a stand for safety has
        # not thereby dropped to 60% full.
        "occupancy": round(sold / sellable, 4) if sellable else 0.0,
        "by_state": by_state,
        "by_stand": by_stand,
    }
