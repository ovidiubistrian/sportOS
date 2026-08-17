"""Drawing a stadium: seat generation, validation and publication.

Three things here are worth reading before using the module.

**Publication is a one-way door.** `publish` freezes a configuration, and every
write below it is refused afterwards by `assert_editable`. Editing a published
layout means `fork`, which deep-copies it into a new draft at the next version.
That is not ceremony: the moment a match snapshots a configuration, the drawing
becomes the explanation of what somebody bought, and an explanation that can be
edited afterwards explains nothing.

**Review is advisory until it is not.** `review` returns findings at two
severities. Warnings — a sector whose declared capacity disagrees with its
seats, a stand with no gate — are shown and can be published through, because a
club mid-setup should not be blocked by its own unfinished work. Errors cannot:
a configuration with no seats at all, or a gate serving nothing, would produce
a match nobody can attend.

**The seat generator is bulk, not clever.** It lays out rows and numbers seats
in one pass and takes explicit lists of the exceptions — wheelchair spaces,
companions, obstructed views, aisle gaps. Clubs know their own ground; the job
here is to save them typing three thousand rows, not to guess the geometry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, ValidationFailed
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

# Which way seat numbers run along a row when the generator lays them out.
NUMBERING_DIRECTIONS = ("LEFT_TO_RIGHT", "RIGHT_TO_LEFT")

# How a row is labelled. Alphabetic skips I and O by convention — they are
# misread as 1 and 0 by stewards working a dark concourse at speed.
ROW_LABEL_STYLES = ("ALPHABETIC", "NUMERIC")

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ"


def _row_label(index: int, style: str, start: str) -> str:
    """The label for row `index`, counting from the club's chosen start."""
    if style == "NUMERIC":
        try:
            first = int(start)
        except ValueError:
            first = 1
        return str(first + index)

    offset = _ALPHABET.index(start.upper()) if start.upper() in _ALPHABET else 0
    position = offset + index
    if position < len(_ALPHABET):
        return _ALPHABET[position]
    # Past Z, double up: AA, AB, ... Rare, but a 40-row stand reaches it.
    first, second = divmod(position - len(_ALPHABET), len(_ALPHABET))
    return _ALPHABET[first] + _ALPHABET[second]


@dataclass(frozen=True, slots=True)
class SeatPlan:
    """What the club asked the generator for."""

    row_count: int
    seats_per_row: int
    row_start_label: str = "A"
    row_label_style: str = "ALPHABETIC"
    first_seat_number: int = 1
    direction: str = "LEFT_TO_RIGHT"

    # Seat positions (1-based, before numbering) after which the count jumps —
    # a gangway. The seats are not created; the numbers continue past them, the
    # way they are painted on the concrete.
    aisle_after: tuple[int, ...] = ()

    # Exceptions, addressed as "ROW:SEAT" — "A:1", "A:2". Explicit rather than
    # derived because there is no rule: the accessible bay is where the ramp
    # happens to come out.
    wheelchair_seats: tuple[str, ...] = ()
    companion_seats: tuple[str, ...] = ()
    obstructed_seats: tuple[str, ...] = ()
    blocked_seats: tuple[str, ...] = ()

    def validate(self) -> None:
        if self.row_count < 1 or self.row_count > 200:
            raise ValidationFailed("A sector needs between 1 and 200 rows.", field="row_count")
        if self.seats_per_row < 1 or self.seats_per_row > 200:
            raise ValidationFailed(
                "A row needs between 1 and 200 seats.", field="seats_per_row"
            )
        if self.row_label_style not in ROW_LABEL_STYLES:
            raise ValidationFailed("Unknown row labelling style.", field="row_label_style")
        if self.direction not in NUMBERING_DIRECTIONS:
            raise ValidationFailed("Unknown numbering direction.", field="direction")
        if self.first_seat_number < 0:
            raise ValidationFailed(
                "Seat numbers start at zero or above.", field="first_seat_number"
            )


@dataclass(slots=True)
class Finding:
    """One thing wrong, or possibly wrong, with a configuration."""

    code: str
    message: str
    severity: str = "WARNING"
    subject: str | None = None


@dataclass(slots=True)
class ConfigurationReview:
    """What the review-and-publish step shows."""

    total_capacity: int = 0
    reserved_seats: int = 0
    general_admission: int = 0
    blocked_seats: int = 0
    accessible_seats: int = 0
    by_stand: list[dict] = field(default_factory=list)
    by_section: list[dict] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "ERROR"]

    @property
    def publishable(self) -> bool:
        return not self.blocking


async def get_configuration(
    session: AsyncSession, tenant_id: UUID, configuration_id: UUID
) -> VenueConfiguration:
    config = await session.scalar(
        select(VenueConfiguration).where(
            VenueConfiguration.tenant_id == tenant_id,
            VenueConfiguration.id == configuration_id,
        )
    )
    if config is None:
        raise NotFound("That stadium configuration does not exist.")
    return config


def assert_editable(config: VenueConfiguration) -> None:
    """The immutability rule, in one place so it cannot be half-applied.

    Every write path below the configuration calls this first. A published
    layout is the record of what was sold from it; changing it would rewrite
    history that tickets, reports and season passes all depend on.
    """
    if config.status != "DRAFT":
        raise Conflict(
            "This configuration is published and cannot be changed. "
            "Create a new version from it instead.",
            configuration_id=str(config.id),
            status=config.status,
        )


async def create_configuration(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    venue_id: UUID,
    name: str,
    created_by: UUID | None = None,
) -> VenueConfiguration:
    venue = await session.scalar(
        select(Venue).where(Venue.tenant_id == tenant_id, Venue.id == venue_id)
    )
    if venue is None:
        raise NotFound("That venue does not exist.")

    highest = await session.scalar(
        select(func.max(VenueConfiguration.version)).where(
            VenueConfiguration.tenant_id == tenant_id,
            VenueConfiguration.venue_id == venue_id,
            VenueConfiguration.name == name,
        )
    )
    config = VenueConfiguration(
        tenant_id=tenant_id,
        venue_id=venue_id,
        name=name,
        version=(highest or 0) + 1,
        status="DRAFT",
        created_by=created_by,
    )
    session.add(config)
    await session.flush()
    return config


async def fork(
    session: AsyncSession,
    tenant_id: UUID,
    configuration_id: UUID,
    *,
    created_by: UUID | None = None,
) -> VenueConfiguration:
    """Deep-copy a configuration into a new editable draft.

    Everything below it is duplicated with fresh identifiers: stands, sections,
    rows, seats, gates, zones and price zones. The copies are new seats, not the
    same seats — which is correct and important. A seat in version 3 and "the
    same" seat in version 4 are different rows, so a match snapshotted from
    version 3 keeps pointing at seats that no later edit can reach.
    """
    source = await get_configuration(session, tenant_id, configuration_id)

    highest = await session.scalar(
        select(func.max(VenueConfiguration.version)).where(
            VenueConfiguration.tenant_id == tenant_id,
            VenueConfiguration.venue_id == source.venue_id,
            VenueConfiguration.name == source.name,
        )
    )
    draft = VenueConfiguration(
        tenant_id=tenant_id,
        venue_id=source.venue_id,
        name=source.name,
        version=(highest or 0) + 1,
        status="DRAFT",
        valid_from=source.valid_from,
        created_by=created_by,
        forked_from_id=source.id,
    )
    session.add(draft)
    await session.flush()

    # Old id → new id, so children can be re-pointed as we go.
    zone_map: dict[UUID, UUID] = {}
    for zone in await _price_zones(session, tenant_id, source.id):
        copy = PriceZone(
            tenant_id=tenant_id,
            configuration_id=draft.id,
            name=zone.name,
            code=zone.code,
            colour=zone.colour,
            display_order=zone.display_order,
        )
        session.add(copy)
        await session.flush()
        zone_map[zone.id] = copy.id

    section_map: dict[UUID, UUID] = {}
    for stand in await _stands(session, tenant_id, source.id):
        stand_copy = Stand(
            tenant_id=tenant_id,
            configuration_id=draft.id,
            name=stand.name,
            code=stand.code,
            display_order=stand.display_order,
            geometry=dict(stand.geometry or {}),
        )
        session.add(stand_copy)
        await session.flush()

        for section in await _sections(session, tenant_id, stand.id):
            section_copy = Section(
                tenant_id=tenant_id,
                stand_id=stand_copy.id,
                price_zone_id=zone_map.get(section.price_zone_id)
                if section.price_zone_id
                else None,
                name=section.name,
                code=section.code,
                kind=section.kind,
                declared_capacity=section.declared_capacity,
                display_order=section.display_order,
                geometry=dict(section.geometry or {}),
            )
            session.add(section_copy)
            await session.flush()
            section_map[section.id] = section_copy.id

            for row in await _rows(session, tenant_id, section.id):
                row_copy = SeatRow(
                    tenant_id=tenant_id,
                    section_id=section_copy.id,
                    label=row.label,
                    display_order=row.display_order,
                )
                session.add(row_copy)
                await session.flush()

                seats = await session.scalars(
                    select(Seat)
                    .where(Seat.tenant_id == tenant_id, Seat.row_id == row.id)
                    .order_by(Seat.seat_index)
                )
                for seat in seats:
                    session.add(
                        Seat(
                            tenant_id=tenant_id,
                            section_id=section_copy.id,
                            row_id=row_copy.id,
                            price_zone_id=zone_map.get(seat.price_zone_id)
                            if seat.price_zone_id
                            else None,
                            label=seat.label,
                            kind=seat.kind,
                            is_blocked=seat.is_blocked,
                            seat_index=seat.seat_index,
                        )
                    )

    zone_lookup: dict[UUID, UUID] = {}
    for zone in await session.scalars(
        select(AccessZone).where(
            AccessZone.tenant_id == tenant_id, AccessZone.configuration_id == source.id
        )
    ):
        copy = AccessZone(
            tenant_id=tenant_id, configuration_id=draft.id, name=zone.name, code=zone.code
        )
        session.add(copy)
        await session.flush()
        zone_lookup[zone.id] = copy.id

    for gate in await session.scalars(
        select(Gate).where(Gate.tenant_id == tenant_id, Gate.configuration_id == source.id)
    ):
        gate_copy = Gate(
            tenant_id=tenant_id,
            configuration_id=draft.id,
            access_zone_id=(
                zone_lookup.get(gate.access_zone_id) if gate.access_zone_id else None
            ),
            name=gate.name,
            code=gate.code,
            kind=gate.kind,
            supporter_side=gate.supporter_side,
            is_accessible=gate.is_accessible,
            note=gate.note,
        )
        session.add(gate_copy)
        await session.flush()

        for link in await session.scalars(
            select(GateSection).where(
                GateSection.tenant_id == tenant_id, GateSection.gate_id == gate.id
            )
        ):
            if link.section_id in section_map:
                session.add(
                    GateSection(
                        tenant_id=tenant_id,
                        gate_id=gate_copy.id,
                        section_id=section_map[link.section_id],
                    )
                )

    await session.flush()
    return draft


async def generate_seats(
    session: AsyncSession,
    tenant_id: UUID,
    section_id: UUID,
    plan: SeatPlan,
    *,
    replace: bool = False,
) -> int:
    """Lay out rows and seats in one pass. Returns how many seats were made.

    `replace` is the destructive path the UI puts behind a confirmation: it
    deletes the sector's rows and seats first. It refuses if the configuration
    is published, so it can never touch anything already sold from.
    """
    plan.validate()

    section = await session.scalar(
        select(Section).where(Section.tenant_id == tenant_id, Section.id == section_id)
    )
    if section is None:
        raise NotFound("That sector does not exist.")
    if section.kind != "RESERVED":
        raise ValidationFailed(
            "General-admission sectors have a capacity, not seats.", field="section_id"
        )

    config = await _configuration_for_section(session, tenant_id, section)
    assert_editable(config)

    existing = await session.scalar(
        select(func.count())
        .select_from(SeatRow)
        .where(SeatRow.tenant_id == tenant_id, SeatRow.section_id == section_id)
    )
    if existing and not replace:
        raise Conflict(
            "This sector already has rows. Regenerating replaces them.",
            section_id=str(section_id),
            rows=existing,
        )
    if existing:
        # Seats cascade from their row.
        await session.execute(
            delete(SeatRow).where(
                SeatRow.tenant_id == tenant_id, SeatRow.section_id == section_id
            )
        )

    wheelchair = set(plan.wheelchair_seats)
    companion = set(plan.companion_seats)
    obstructed = set(plan.obstructed_seats)
    blocked = set(plan.blocked_seats)
    aisles = set(plan.aisle_after)

    made = 0
    for row_index in range(plan.row_count):
        label = _row_label(row_index, plan.row_label_style, plan.row_start_label)
        row = SeatRow(
            tenant_id=tenant_id, section_id=section_id, label=label, display_order=row_index
        )
        session.add(row)
        await session.flush()

        # Walk the physical positions; `number` is what gets painted, and it
        # advances an extra step at every gangway.
        number = plan.first_seat_number
        for position in range(plan.seats_per_row):
            seat_label = str(number)
            address = f"{label}:{seat_label}"

            kind = "STANDARD"
            if address in wheelchair:
                kind = "WHEELCHAIR"
            elif address in companion:
                kind = "COMPANION"
            elif address in obstructed:
                kind = "OBSTRUCTED_VIEW"

            index = (
                position
                if plan.direction == "LEFT_TO_RIGHT"
                else plan.seats_per_row - 1 - position
            )
            session.add(
                Seat(
                    tenant_id=tenant_id,
                    section_id=section_id,
                    row_id=row.id,
                    label=seat_label,
                    kind=kind,
                    is_blocked=address in blocked,
                    seat_index=index,
                )
            )
            made += 1
            number += 2 if (position + 1) in aisles else 1

    await session.flush()
    await _resync_section_capacity(session, tenant_id, section_id)
    return made


async def assign_price_zone(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    price_zone_id: UUID | None,
    section_ids: list[UUID] | None = None,
    seat_ids: list[UUID] | None = None,
) -> int:
    """Put sectors or individual seats into a price zone. Returns the count.

    Both granularities matter. A club prices whole sectors as a rule and then
    lifts the front four rows of the main stand into Category 1, which is a
    seat-level decision that would otherwise force the sector to be split.
    """
    touched = 0
    if section_ids:
        sections = list(
            await session.scalars(
                select(Section).where(
                    Section.tenant_id == tenant_id, Section.id.in_(section_ids)
                )
            )
        )
        for section in sections:
            config = await _configuration_for_section(session, tenant_id, section)
            assert_editable(config)
            section.price_zone_id = price_zone_id
            touched += 1

    if seat_ids:
        seats = list(
            await session.scalars(
                select(Seat).where(Seat.tenant_id == tenant_id, Seat.id.in_(seat_ids))
            )
        )
        for seat in seats:
            section = await session.scalar(
                select(Section).where(
                    Section.tenant_id == tenant_id, Section.id == seat.section_id
                )
            )
            if section is not None:
                assert_editable(await _configuration_for_section(session, tenant_id, section))
            seat.price_zone_id = price_zone_id
            touched += 1

    await session.flush()
    return touched


async def set_seats_blocked(
    session: AsyncSession, tenant_id: UUID, seat_ids: list[UUID], *, blocked: bool
) -> int:
    seats = list(
        await session.scalars(
            select(Seat).where(Seat.tenant_id == tenant_id, Seat.id.in_(seat_ids))
        )
    )
    for seat in seats:
        section = await session.scalar(
            select(Section).where(Section.tenant_id == tenant_id, Section.id == seat.section_id)
        )
        if section is not None:
            assert_editable(await _configuration_for_section(session, tenant_id, section))
        seat.is_blocked = blocked
    await session.flush()
    return len(seats)


async def review(
    session: AsyncSession, tenant_id: UUID, configuration_id: UUID
) -> ConfigurationReview:
    """Everything the publish step shows, and everything that would stop it."""
    config = await get_configuration(session, tenant_id, configuration_id)
    result = ConfigurationReview()

    stands = await _stands(session, tenant_id, configuration_id)
    if not stands:
        result.findings.append(
            Finding("NO_STANDS", "This configuration has no stands.", "ERROR")
        )

    gated_sections: set[UUID] = set()
    gates = list(
        await session.scalars(
            select(Gate).where(
                Gate.tenant_id == tenant_id, Gate.configuration_id == configuration_id
            )
        )
    )
    for gate in gates:
        served = list(
            await session.scalars(
                select(GateSection.section_id).where(
                    GateSection.tenant_id == tenant_id, GateSection.gate_id == gate.id
                )
            )
        )
        gated_sections.update(served)
        if not served:
            result.findings.append(
                Finding(
                    "GATE_WITHOUT_SECTIONS",
                    f"Gate {gate.code} does not serve any sector.",
                    "WARNING",
                    subject=str(gate.id),
                )
            )
    if not gates:
        result.findings.append(
            Finding("NO_GATES", "This configuration has no gates.", "WARNING")
        )

    for stand in stands:
        stand_capacity = 0
        sections = await _sections(session, tenant_id, stand.id)
        if not sections:
            result.findings.append(
                Finding(
                    "STAND_WITHOUT_SECTIONS",
                    f"{stand.name} has no sectors.",
                    "WARNING",
                    subject=str(stand.id),
                )
            )

        for section in sections:
            if section.kind == "GENERAL_ADMISSION":
                capacity = section.declared_capacity
                result.general_admission += capacity
            else:
                counts = (
                    await session.execute(
                        select(
                            func.count(),
                            func.count().filter(Seat.is_blocked.is_(True)),
                            func.count().filter(Seat.kind == "WHEELCHAIR"),
                        ).where(Seat.tenant_id == tenant_id, Seat.section_id == section.id)
                    )
                ).one()
                total, blocked, accessible = counts
                capacity = total - blocked
                result.reserved_seats += total
                result.blocked_seats += blocked
                result.accessible_seats += accessible

                if total == 0:
                    result.findings.append(
                        Finding(
                            "SECTION_WITHOUT_SEATS",
                            f"{section.name} is reserved seating but has no seats.",
                            "WARNING",
                            subject=str(section.id),
                        )
                    )
                elif section.declared_capacity and section.declared_capacity != total:
                    result.findings.append(
                        Finding(
                            "SECTION_CAPACITY_MISMATCH",
                            f"{section.name} expects {section.declared_capacity} seats "
                            f"but has {total}.",
                            "WARNING",
                            subject=str(section.id),
                        )
                    )

            if section.price_zone_id is None:
                result.findings.append(
                    Finding(
                        "SECTION_WITHOUT_PRICE_ZONE",
                        f"{section.name} has no price zone, so it cannot be priced.",
                        "WARNING",
                        subject=str(section.id),
                    )
                )
            if section.id not in gated_sections:
                result.findings.append(
                    Finding(
                        "SECTION_WITHOUT_GATE",
                        f"{section.name} is not reachable through any gate.",
                        "WARNING",
                        subject=str(section.id),
                    )
                )

            stand_capacity += capacity
            result.by_section.append(
                {
                    "id": str(section.id),
                    "stand": stand.name,
                    "name": section.name,
                    "code": section.code,
                    "kind": section.kind,
                    "capacity": capacity,
                }
            )

        result.total_capacity += stand_capacity
        result.by_stand.append(
            {"id": str(stand.id), "name": stand.name, "capacity": stand_capacity}
        )

    if result.total_capacity == 0:
        result.findings.append(
            Finding("NO_CAPACITY", "This configuration sells nothing.", "ERROR")
        )

    venue = await session.scalar(
        select(Venue).where(Venue.tenant_id == tenant_id, Venue.id == config.venue_id)
    )
    if venue and venue.expected_capacity and venue.expected_capacity != result.total_capacity:
        result.findings.append(
            Finding(
                "VENUE_CAPACITY_MISMATCH",
                f"The ground is recorded as holding {venue.expected_capacity}, "
                f"but this configuration totals {result.total_capacity}.",
                "WARNING",
            )
        )

    return result


async def publish(
    session: AsyncSession, tenant_id: UUID, configuration_id: UUID
) -> VenueConfiguration:
    """Freeze a draft. Refuses on blocking findings."""
    config = await get_configuration(session, tenant_id, configuration_id)
    if config.status == "PUBLISHED":
        return config
    if config.status == "ARCHIVED":
        raise Conflict("An archived configuration cannot be published again.")

    result = await review(session, tenant_id, configuration_id)
    if not result.publishable:
        raise ValidationFailed(
            "This configuration cannot be published yet.",
            findings=[
                {"code": f.code, "message": f.message, "subject": f.subject}
                for f in result.blocking
            ],
        )

    config.total_capacity = result.total_capacity
    config.status = "PUBLISHED"
    config.published_at = datetime.now(UTC)
    await session.flush()
    return config


# --- internals -------------------------------------------------------------


async def _price_zones(
    session: AsyncSession, tenant_id: UUID, configuration_id: UUID
) -> list[PriceZone]:
    return list(
        await session.scalars(
            select(PriceZone)
            .where(
                PriceZone.tenant_id == tenant_id,
                PriceZone.configuration_id == configuration_id,
            )
            .order_by(PriceZone.display_order)
        )
    )


async def _stands(
    session: AsyncSession, tenant_id: UUID, configuration_id: UUID
) -> list[Stand]:
    return list(
        await session.scalars(
            select(Stand)
            .where(Stand.tenant_id == tenant_id, Stand.configuration_id == configuration_id)
            .order_by(Stand.display_order)
        )
    )


async def _sections(session: AsyncSession, tenant_id: UUID, stand_id: UUID) -> list[Section]:
    return list(
        await session.scalars(
            select(Section)
            .where(Section.tenant_id == tenant_id, Section.stand_id == stand_id)
            .order_by(Section.display_order)
        )
    )


async def _rows(session: AsyncSession, tenant_id: UUID, section_id: UUID) -> list[SeatRow]:
    return list(
        await session.scalars(
            select(SeatRow)
            .where(SeatRow.tenant_id == tenant_id, SeatRow.section_id == section_id)
            .order_by(SeatRow.display_order)
        )
    )


async def _configuration_for_section(
    session: AsyncSession, tenant_id: UUID, section: Section
) -> VenueConfiguration:
    stand = await session.scalar(
        select(Stand).where(Stand.tenant_id == tenant_id, Stand.id == section.stand_id)
    )
    if stand is None:
        raise NotFound("That sector's stand does not exist.")
    return await get_configuration(session, tenant_id, stand.configuration_id)


async def _resync_section_capacity(
    session: AsyncSession, tenant_id: UUID, section_id: UUID
) -> None:
    """Keep `declared_capacity` honest after a generator run.

    The club's expected number is what the review compares against, but once
    seats exist the seats are the truth, and leaving a stale expectation would
    make every later review report a mismatch that is not real.
    """
    total = await session.scalar(
        select(func.count())
        .select_from(Seat)
        .where(Seat.tenant_id == tenant_id, Seat.section_id == section_id)
    )
    section = await session.scalar(
        select(Section).where(Section.tenant_id == tenant_id, Section.id == section_id)
    )
    if section is not None:
        section.declared_capacity = int(total or 0)


def parse_seat_address(value: str) -> tuple[str, str]:
    """ "A:12" → ("A", "12"). Raises rather than guessing at malformed input."""
    match = re.fullmatch(r"\s*([A-Za-z0-9]{1,12})\s*:\s*([0-9]{1,12})\s*", value)
    if not match:
        raise ValidationFailed(f"{value!r} is not a seat address like 'A:12'.", field="seat")
    return match.group(1).upper(), match.group(2)
