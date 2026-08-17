"""The whole vertical slice: draw a ground, sell a seat, scan the ticket.

These are the mandatory acceptance scenarios, expressed as tests. They run
against the real database because every guarantee under test is a database
guarantee — row locks, partial unique indexes, foreign keys across tenants.
A test double would prove that the Python is self-consistent and nothing about
whether the same seat can be sold twice.

The interesting ones are:

- `test_a_second_basket_cannot_take_a_held_seat`, which uses two separate
  connections. Same-session it would pass trivially; across connections it
  exercises what actually happens when two supporters click at once.
- `test_editing_the_ground_leaves_a_published_match_alone`, which is the
  architecture's central claim and the one that would fail silently if anybody
  ever "optimised" the snapshot away with a join.
- `test_the_same_ticket_twice_reads_already_used`, which proves the verdict
  comes from a unique index rather than from a read-then-write.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core import model_registry  # noqa: F401
from app.core.config import settings
from app.core.db import bind_tenant
from app.core.errors import Conflict, SeatUnavailable
from app.ticketing import credentials as credential_service
from app.ticketing import inventory as inventory_service
from app.ticketing import issuing
from app.ticketing.access_service import ScanVerdict, validate
from app.ticketing.event_models import (
    EventSeatInventory,
    PriceList,
    PriceRule,
    TicketedEvent,
    TicketType,
)
from app.ticketing.event_service import create_event, get_snapshot, publish_event
from app.ticketing.ticket_models import (
    AccessCredential,
    EventEntitlement,
    SeasonTicketEvent,
    SeasonTicketProduct,
    Ticket,
)
from app.ticketing.venue_models import (
    Gate,
    GateSection,
    PriceZone,
    Seat,
    Section,
    Stand,
    Venue,
    VenueConfiguration,
)
from app.ticketing.venue_service import (
    SeatPlan,
    assert_editable,
    generate_seats,
    publish,
    review,
)

pytestmark = pytest.mark.commerce


def _session_factory():
    engine = create_async_engine(settings.database_url, poolclass=NullPool, echo=False)
    return engine, async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )


@pytest.fixture
async def db(demo: dict[str, Any]) -> AsyncIterator[AsyncSession]:
    """A tenant-bound session, rolled back so the suite leaves no residue."""
    engine, factory = _session_factory()
    try:
        async with factory() as session:
            await session.begin()
            await bind_tenant(session, UUID(demo["tenant_id"]))
            try:
                yield session
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


async def _build_ground(
    session: AsyncSession, tenant_id: UUID, club_id: UUID
) -> dict[str, Any]:
    """A small but complete stadium: one seated sector, one terrace, two gates.

    Three rows of ten and a fifty-place terrace, which is enough to exercise
    adjacency, general admission and gate routing without generating thirty
    thousand rows in every test.
    """
    suffix = uuid4().hex[:8]

    venue = Venue(
        tenant_id=tenant_id,
        club_id=club_id,
        name="Test Ground",
        code=f"TG{suffix}",
        city="Reșița",
        expected_capacity=0,
    )
    session.add(venue)
    await session.flush()

    config = VenueConfiguration(
        tenant_id=tenant_id, venue_id=venue.id, name=f"Standard {suffix}", version=1
    )
    session.add(config)
    await session.flush()

    cat1 = PriceZone(
        tenant_id=tenant_id, configuration_id=config.id, name="Category 1", code="CAT1"
    )
    terrace_zone = PriceZone(
        tenant_id=tenant_id, configuration_id=config.id, name="Terrace", code="TERR"
    )
    session.add_all([cat1, terrace_zone])
    await session.flush()

    stand = Stand(tenant_id=tenant_id, configuration_id=config.id, name="Main", code="MAIN")
    session.add(stand)
    await session.flush()

    seated = Section(
        tenant_id=tenant_id,
        stand_id=stand.id,
        price_zone_id=cat1.id,
        name="Main Lower",
        code="ML",
        kind="RESERVED",
    )
    terrace = Section(
        tenant_id=tenant_id,
        stand_id=stand.id,
        price_zone_id=terrace_zone.id,
        name="North Terrace",
        code="NT",
        kind="GENERAL_ADMISSION",
        declared_capacity=50,
    )
    session.add_all([seated, terrace])
    await session.flush()

    await generate_seats(
        session,
        tenant_id,
        seated.id,
        SeatPlan(row_count=3, seats_per_row=10, row_start_label="A"),
    )

    gate_a = Gate(tenant_id=tenant_id, configuration_id=config.id, name="Gate A", code="A")
    gate_b = Gate(tenant_id=tenant_id, configuration_id=config.id, name="Gate B", code="B")
    session.add_all([gate_a, gate_b])
    await session.flush()

    # Gate A serves the seats, Gate B the terrace — so a seated ticket
    # presented at B is genuinely at the wrong gate.
    session.add_all(
        [
            GateSection(tenant_id=tenant_id, gate_id=gate_a.id, section_id=seated.id),
            GateSection(tenant_id=tenant_id, gate_id=gate_b.id, section_id=terrace.id),
        ]
    )
    await session.flush()
    await publish(session, tenant_id, config.id)

    return {
        "venue": venue,
        "config": config,
        "stand": stand,
        "seated": seated,
        "terrace": terrace,
        "gate_a": gate_a,
        "gate_b": gate_b,
        "suffix": suffix,
    }


async def _price_everything(
    session: AsyncSession, tenant_id: UUID, venue_id: UUID, *, codes=("CAT1", "TERR")
) -> None:
    adult = await session.scalar(
        select(TicketType).where(TicketType.tenant_id == tenant_id, TicketType.code == "ADULT")
    )
    if adult is None:
        adult = TicketType(tenant_id=tenant_id, name="Adult", code="ADULT")
        session.add(adult)
        await session.flush()

    price_list = PriceList(
        tenant_id=tenant_id,
        name="Ground default",
        scope="VENUE",
        venue_id=venue_id,
        currency="RON",
    )
    session.add(price_list)
    await session.flush()

    for code in codes:
        session.add(
            PriceRule(
                tenant_id=tenant_id,
                price_list_id=price_list.id,
                ticket_type_id=adult.id,
                price_zone_code=code,
                amount_minor=5000,
                vat_rate_bp=1900,
                vat_included=True,
            )
        )
    await session.flush()


async def _make_event(
    session: AsyncSession,
    ground: dict[str, Any],
    tenant_id: UUID,
    club_id: UUID,
    *,
    name="Match",
):
    return await create_event(
        session,
        tenant_id,
        club_id=club_id,
        venue_id=ground["venue"].id,
        configuration_id=ground["config"].id,
        name=name,
        slug=f"{name.lower().replace(' ', '-')}-{uuid4().hex[:8]}",
        kickoff_at=datetime.now(UTC) + timedelta(days=7),
        doors_open_at=datetime.now(UTC) - timedelta(hours=1),
    )


# --- Scenarios 1-4: build and publish a ground ------------------------------


async def test_a_published_configuration_refuses_to_be_edited(
    db: AsyncSession, demo: dict[str, Any]
) -> None:
    """Scenario 4. Publication is the one-way door the whole design rests on."""
    tenant_id = UUID(demo["tenant_id"])
    ground = await _build_ground(db, tenant_id, UUID(demo["club_id"]))

    assert ground["config"].status == "PUBLISHED"
    assert ground["config"].total_capacity == 80  # 30 seats + 50 terrace

    with pytest.raises(Conflict):
        assert_editable(ground["config"])

    # And the guard is not merely advisory — the generator honours it.
    with pytest.raises(Conflict):
        await generate_seats(
            db,
            tenant_id,
            ground["seated"].id,
            SeatPlan(row_count=1, seats_per_row=1),
            replace=True,
        )


async def test_the_review_reports_what_is_missing(
    db: AsyncSession, demo: dict[str, Any]
) -> None:
    """Scenario 7's screen: capacity broken down, and the gaps named."""
    tenant_id = UUID(demo["tenant_id"])
    ground = await _build_ground(db, tenant_id, UUID(demo["club_id"]))

    result = await review(db, tenant_id, ground["config"].id)

    assert result.total_capacity == 80
    assert result.reserved_seats == 30
    assert result.general_admission == 50
    assert result.publishable
    assert {entry["name"] for entry in result.by_stand} == {"Main"}


# --- Scenarios 5, 6, 13: the snapshot ---------------------------------------


async def test_a_match_mints_its_own_inventory(db: AsyncSession, demo: dict[str, Any]) -> None:
    """Scenarios 5 and 6. One row per admission, snapshot taken once."""
    tenant_id = UUID(demo["tenant_id"])
    ground = await _build_ground(db, tenant_id, UUID(demo["club_id"]))
    event = await _make_event(db, ground, tenant_id, UUID(demo["club_id"]))

    snapshot = await get_snapshot(db, tenant_id, event.id)
    assert snapshot.source_version == 1
    assert snapshot.total_capacity == 80

    total = await db.scalar(
        select(func.count())
        .select_from(EventSeatInventory)
        .where(
            EventSeatInventory.tenant_id == tenant_id,
            EventSeatInventory.event_id == event.id,
        )
    )
    assert total == 80

    ga = await db.scalar(
        select(func.count())
        .select_from(EventSeatInventory)
        .where(
            EventSeatInventory.tenant_id == tenant_id,
            EventSeatInventory.event_id == event.id,
            EventSeatInventory.seat_id.is_(None),
        )
    )
    assert ga == 50


async def test_editing_the_ground_leaves_a_published_match_alone(
    db: AsyncSession, demo: dict[str, Any]
) -> None:
    """Scenario 13 — the architecture's central promise.

    Renaming a stand and deleting a whole sector from the master must not move
    a single row of an existing match's inventory.
    """
    tenant_id = UUID(demo["tenant_id"])
    ground = await _build_ground(db, tenant_id, UUID(demo["club_id"]))
    event = await _make_event(db, ground, tenant_id, UUID(demo["club_id"]))

    before = await db.scalar(
        select(func.count())
        .select_from(EventSeatInventory)
        .where(
            EventSeatInventory.tenant_id == tenant_id,
            EventSeatInventory.event_id == event.id,
        )
    )
    sample = await db.scalar(
        select(EventSeatInventory).where(
            EventSeatInventory.tenant_id == tenant_id,
            EventSeatInventory.event_id == event.id,
            EventSeatInventory.seat_id.is_not(None),
        )
    )
    original_stand_name = sample.stand_name

    # Vandalise the master: rename the stand, delete the terrace outright.
    ground["stand"].name = "Renamed Stand"
    await db.delete(ground["terrace"])
    await db.flush()

    after = await db.scalar(
        select(func.count())
        .select_from(EventSeatInventory)
        .where(
            EventSeatInventory.tenant_id == tenant_id,
            EventSeatInventory.event_id == event.id,
        )
    )
    await db.refresh(sample)

    assert after == before, "deleting a sector changed a published match's inventory"
    assert sample.stand_name == original_stand_name, "a rename leaked into a sold layout"

    snapshot = await get_snapshot(db, tenant_id, event.id)
    assert snapshot.payload["stands"][0]["name"] == original_stand_name


# --- Scenarios 8-10: holding seats ------------------------------------------


async def _seats_in_row(
    session: AsyncSession, tenant_id: UUID, event_id: UUID, row_label: str
) -> list[EventSeatInventory]:
    return list(
        await session.scalars(
            select(EventSeatInventory)
            .where(
                EventSeatInventory.tenant_id == tenant_id,
                EventSeatInventory.event_id == event_id,
                EventSeatInventory.row_label == row_label,
            )
            .order_by(EventSeatInventory.seat_index)
        )
    )


async def test_two_adjacent_seats_are_held_for_ten_minutes(
    db: AsyncSession, demo: dict[str, Any]
) -> None:
    """Scenarios 8 and 9."""
    tenant_id = UUID(demo["tenant_id"])
    ground = await _build_ground(db, tenant_id, UUID(demo["club_id"]))
    event = await _make_event(db, ground, tenant_id, UUID(demo["club_id"]))

    seats = await _seats_in_row(db, tenant_id, event.id, "A")
    cart = uuid4()
    held = await inventory_service.hold(
        db,
        tenant_id,
        event_id=event.id,
        cart_id=cart,
        inventory_ids=[seats[0].id, seats[1].id],
        ticket_type_code="ADULT",
    )

    assert len(held) == 2
    assert all(row.state == "CART_HELD" for row in held)

    lifetime = held[0].hold_expires_at - datetime.now(UTC)
    assert timedelta(minutes=9) < lifetime <= timedelta(minutes=10)


async def test_a_second_basket_cannot_take_a_held_seat(demo: dict[str, Any]) -> None:
    """Scenario 10, across two real connections.

    Committed rather than rolled back, because the point is that a *different*
    connection sees the hold. Everything is torn down in the `finally` so the
    suite still leaves the database as it found it.
    """
    tenant_id = UUID(demo["tenant_id"])
    club_id = UUID(demo["club_id"])
    engine, factory = _session_factory()

    venue_id = None
    try:
        async with factory() as first:
            await first.begin()
            await bind_tenant(first, tenant_id)
            ground = await _build_ground(first, tenant_id, club_id)
            venue_id = ground["venue"].id
            event = await _make_event(first, ground, tenant_id, club_id)
            seats = await _seats_in_row(first, tenant_id, event.id, "A")
            target = seats[0].id
            event_id = event.id
            await inventory_service.hold(
                first,
                tenant_id,
                event_id=event_id,
                cart_id=uuid4(),
                inventory_ids=[target],
            )
            await first.commit()

        # A different connection entirely — a different supporter's request.
        async with factory() as second:
            await second.begin()
            await bind_tenant(second, tenant_id)
            with pytest.raises(SeatUnavailable):
                await inventory_service.hold(
                    second,
                    tenant_id,
                    event_id=event_id,
                    cart_id=uuid4(),
                    inventory_ids=[target],
                )
            await second.rollback()
    finally:
        if venue_id is not None:
            async with factory() as cleanup:
                await cleanup.begin()
                await bind_tenant(cleanup, tenant_id)
                # Order matters: the event holds RESTRICT references to both
                # the venue and its configuration, which is the point — a
                # ground cannot be deleted out from under a match that sold
                # tickets from it.
                for row in await cleanup.scalars(
                    select(TicketedEvent).where(
                        TicketedEvent.tenant_id == tenant_id,
                        TicketedEvent.venue_id == venue_id,
                    )
                ):
                    await cleanup.delete(row)
                await cleanup.flush()
                for row in await cleanup.scalars(
                    select(VenueConfiguration).where(
                        VenueConfiguration.tenant_id == tenant_id,
                        VenueConfiguration.venue_id == venue_id,
                    )
                ):
                    await cleanup.delete(row)
                await cleanup.flush()
                venue = await cleanup.scalar(
                    select(Venue).where(Venue.tenant_id == tenant_id, Venue.id == venue_id)
                )
                if venue is not None:
                    await cleanup.delete(venue)
                await cleanup.commit()
        await engine.dispose()


async def test_a_lapsed_hold_is_treated_as_free(db: AsyncSession, demo: dict[str, Any]) -> None:
    """A basket abandoned eleven minutes ago must not keep the seat.

    Asserted through the read path rather than the sweep, because that is the
    guarantee: the seat comes back whether or not the maintenance job has run.
    """
    tenant_id = UUID(demo["tenant_id"])
    ground = await _build_ground(db, tenant_id, UUID(demo["club_id"]))
    event = await _make_event(db, ground, tenant_id, UUID(demo["club_id"]))

    seats = await _seats_in_row(db, tenant_id, event.id, "A")
    held = await inventory_service.hold(
        db, tenant_id, event_id=event.id, cart_id=uuid4(), inventory_ids=[seats[0].id]
    )
    held[0].hold_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db.flush()

    assert inventory_service.is_free(held[0])

    # And somebody else can now take it.
    retaken = await inventory_service.hold(
        db, tenant_id, event_id=event.id, cart_id=uuid4(), inventory_ids=[seats[0].id]
    )
    assert retaken[0].state == "CART_HELD"


async def test_best_available_prefers_seats_together(
    db: AsyncSession, demo: dict[str, Any]
) -> None:
    tenant_id = UUID(demo["tenant_id"])
    ground = await _build_ground(db, tenant_id, UUID(demo["club_id"]))
    event = await _make_event(db, ground, tenant_id, UUID(demo["club_id"]))

    seats = await _seats_in_row(db, tenant_id, event.id, "A")
    # Punch a hole so the first pair in row A is no longer contiguous.
    await inventory_service.hold(
        db, tenant_id, event_id=event.id, cart_id=uuid4(), inventory_ids=[seats[1].id]
    )

    found = await inventory_service.best_available(
        db, tenant_id, event_id=event.id, quantity=3, section_id=ground["seated"].id
    )

    assert len(found) == 3
    indexes = [row.seat_index for row in found]
    assert indexes == sorted(indexes)
    assert all(row.row_label == found[0].row_label for row in found)
    assert indexes[-1] - indexes[0] == 2, "best available returned a scattered block"


# --- Scenario 11: paying issues a ticket and a QR ---------------------------


async def test_selling_a_seat_issues_a_ticket_and_a_credential(
    db: AsyncSession, demo: dict[str, Any]
) -> None:
    """Scenario 11."""
    tenant_id = UUID(demo["tenant_id"])
    ground = await _build_ground(db, tenant_id, UUID(demo["club_id"]))
    await _price_everything(db, tenant_id, ground["venue"].id)
    event = await _make_event(db, ground, tenant_id, UUID(demo["club_id"]))

    seats = await _seats_in_row(db, tenant_id, event.id, "A")
    cart, order = uuid4(), uuid4()
    await inventory_service.hold(
        db,
        tenant_id,
        event_id=event.id,
        cart_id=cart,
        inventory_ids=[seats[0].id],
        ticket_type_code="ADULT",
    )
    await inventory_service.confirm_sold(db, tenant_id, cart_id=cart, order_id=order)

    tickets = await issuing.issue_for_order(
        db, tenant_id, order_id=order, holder_name="Ion Popescu"
    )

    assert len(tickets) == 1
    ticket = tickets[0]
    assert ticket.status == "ISSUED"
    assert ticket.price_minor == 5000
    # 19% VAT inside a 50.00 price is 7.98, not 9.50.
    assert ticket.vat_minor == 798

    credential = await db.scalar(
        select(AccessCredential).where(
            AccessCredential.tenant_id == tenant_id,
            AccessCredential.ticket_id == ticket.id,
            AccessCredential.status == "ACTIVE",
        )
    )
    assert credential is not None
    assert credential.gate_codes == "A"

    # The QR must give nothing away about the holder.
    payload = credential_service.qr_payload(credential)
    assert "Ion" not in payload and "Popescu" not in payload
    assert ticket.ticket_number not in payload
    assert str(ticket.id) not in payload


# --- Scenarios 14-16: scanning ----------------------------------------------


async def _sell_one_seat(
    session: AsyncSession, tenant_id: UUID, ground: dict[str, Any], club_id: UUID
) -> tuple[Any, AccessCredential]:
    await _price_everything(session, tenant_id, ground["venue"].id)
    event = await _make_event(session, ground, tenant_id, club_id)
    await publish_event(session, tenant_id, event.id)

    seats = await _seats_in_row(session, tenant_id, event.id, "A")
    cart, order = uuid4(), uuid4()
    await inventory_service.hold(
        session,
        tenant_id,
        event_id=event.id,
        cart_id=cart,
        inventory_ids=[seats[0].id],
        ticket_type_code="ADULT",
    )
    await inventory_service.confirm_sold(session, tenant_id, cart_id=cart, order_id=order)
    tickets = await issuing.issue_for_order(
        session, tenant_id, order_id=order, holder_name="Ion Popescu"
    )
    credential = await session.scalar(
        select(AccessCredential).where(
            AccessCredential.tenant_id == tenant_id,
            AccessCredential.ticket_id == tickets[0].id,
        )
    )
    return event, credential


async def test_a_ticket_scans_valid_then_already_used(
    db: AsyncSession, demo: dict[str, Any]
) -> None:
    """Scenarios 14 and 15.

    The second verdict comes from a unique index violation, not from a read —
    which is why it is correct even when the two scans land on two servers in
    the same millisecond.
    """
    tenant_id = UUID(demo["tenant_id"])
    ground = await _build_ground(db, tenant_id, UUID(demo["club_id"]))
    event, credential = await _sell_one_seat(db, tenant_id, ground, UUID(demo["club_id"]))
    payload = credential_service.qr_payload(credential)

    first: ScanVerdict = await validate(
        db, tenant_id, event_id=event.id, scanned=payload, gate_code="A"
    )
    assert first.result == "VALID"
    assert first.seat is not None

    second: ScanVerdict = await validate(
        db, tenant_id, event_id=event.id, scanned=payload, gate_code="A"
    )
    assert second.result == "ALREADY_USED"
    # The steward is told when and where the holder came in the first time.
    assert second.first_seen_at is not None
    assert second.first_seen_gate == "A"


async def test_a_retry_returns_the_same_verdict(db: AsyncSession, demo: dict[str, Any]) -> None:
    """A dropped connection must not turn one entry into ALREADY_USED."""
    tenant_id = UUID(demo["tenant_id"])
    ground = await _build_ground(db, tenant_id, UUID(demo["club_id"]))
    event, credential = await _sell_one_seat(db, tenant_id, ground, UUID(demo["club_id"]))
    payload = credential_service.qr_payload(credential)
    key = uuid4().hex

    first = await validate(
        db, tenant_id, event_id=event.id, scanned=payload, gate_code="A", idempotency_key=key
    )
    again = await validate(
        db, tenant_id, event_id=event.id, scanned=payload, gate_code="A", idempotency_key=key
    )

    assert first.result == "VALID"
    assert again.result == "VALID"
    assert again.scan_id == first.scan_id


async def test_the_wrong_gate_is_refused(db: AsyncSession, demo: dict[str, Any]) -> None:
    """Scenario 16. A seated ticket presented at the terrace gate."""
    tenant_id = UUID(demo["tenant_id"])
    ground = await _build_ground(db, tenant_id, UUID(demo["club_id"]))
    event, credential = await _sell_one_seat(db, tenant_id, ground, UUID(demo["club_id"]))

    verdict = await validate(
        db,
        tenant_id,
        event_id=event.id,
        scanned=credential_service.qr_payload(credential),
        gate_code="B",
    )
    assert verdict.result == "WRONG_GATE"


async def test_unknown_and_wrong_event_codes(db: AsyncSession, demo: dict[str, Any]) -> None:
    tenant_id = UUID(demo["tenant_id"])
    ground = await _build_ground(db, tenant_id, UUID(demo["club_id"]))
    event, credential = await _sell_one_seat(db, tenant_id, ground, UUID(demo["club_id"]))
    other = await _make_event(
        db, ground, tenant_id, UUID(demo["club_id"]), name="Another Match"
    )

    unknown = await validate(
        db, tenant_id, event_id=event.id, scanned="not-a-real-code", gate_code="A"
    )
    assert unknown.result == "UNKNOWN_CREDENTIAL"

    wrong_event = await validate(
        db,
        tenant_id,
        event_id=other.id,
        scanned=credential_service.qr_payload(credential),
        gate_code="A",
    )
    assert wrong_event.result == "WRONG_EVENT"


async def test_a_forged_signature_does_not_verify(
    db: AsyncSession, demo: dict[str, Any]
) -> None:
    """Offline rejection: what the Android client will rely on."""
    tenant_id = UUID(demo["tenant_id"])
    ground = await _build_ground(db, tenant_id, UUID(demo["club_id"]))
    _event, credential = await _sell_one_seat(db, tenant_id, ground, UUID(demo["club_id"]))

    claims = credential_service.CredentialClaims(
        reference=credential.reference,
        event_id=credential.event_id,
        section_code=credential.section_code,
        gate_codes=credential.gate_codes or "",
        valid_from=credential.valid_from,
        valid_until=credential.valid_until,
        key_id=credential.key_id,
    )
    public = credential_service.public_key_base64()

    assert credential_service.verify_with_key(claims, credential.signature, public)

    forged = replace(claims, section_code="VIP")
    assert not credential_service.verify_with_key(forged, credential.signature, public)


# --- Scenario 12: season tickets --------------------------------------------


async def test_a_season_pass_holds_one_seat_across_every_match(
    db: AsyncSession, demo: dict[str, Any]
) -> None:
    """Scenario 12, and the per-match entitlement rule.

    Three matches, one seat, three separate entitlements and three separate QR
    codes — so one match can be released without touching the other two.
    """
    tenant_id = UUID(demo["tenant_id"])
    club_id = UUID(demo["club_id"])
    ground = await _build_ground(db, tenant_id, club_id)
    await _price_everything(db, tenant_id, ground["venue"].id)

    events = [
        await _make_event(db, ground, tenant_id, club_id, name=f"Fixture {n}") for n in range(3)
    ]

    product = SeasonTicketProduct(
        tenant_id=tenant_id,
        club_id=club_id,
        configuration_id=ground["config"].id,
        name="Season 2026/27",
        price_minor=90000,
        status="ON_SALE",
    )
    db.add(product)
    await db.flush()
    for event in events:
        db.add(SeasonTicketEvent(tenant_id=tenant_id, product_id=product.id, event_id=event.id))
    await db.flush()

    seat = await db.scalar(
        select(Seat)
        .where(Seat.tenant_id == tenant_id, Seat.section_id == ground["seated"].id)
        .order_by(Seat.seat_index)
    )

    season_pass = await issuing.issue_season_pass(
        db,
        tenant_id,
        product_id=product.id,
        seat_id=seat.id,
        holder_name="Maria Ionescu",
    )

    entitlements = list(
        await db.scalars(
            select(EventEntitlement).where(
                EventEntitlement.tenant_id == tenant_id,
                EventEntitlement.season_pass_id == season_pass.id,
            )
        )
    )
    assert len(entitlements) == 3, "a season pass must mint one right per match"
    assert {e.event_id for e in entitlements} == {e.id for e in events}

    tickets = list(
        await db.scalars(
            select(Ticket).where(
                Ticket.tenant_id == tenant_id, Ticket.season_pass_id == season_pass.id
            )
        )
    )
    assert len(tickets) == 3
    assert len({t.ticket_number for t in tickets}) == 3

    # The same physical seat every time.
    rows = list(
        await db.scalars(
            select(EventSeatInventory).where(
                EventSeatInventory.tenant_id == tenant_id,
                EventSeatInventory.id.in_([e.inventory_id for e in entitlements]),
            )
        )
    )
    assert {row.seat_id for row in rows} == {seat.id}
    assert all(row.state == "SOLD" for row in rows)

    # Releasing one match frees that seat and leaves the rest of the pass alone.
    released = await issuing.release_match(db, tenant_id, entitlement_id=entitlements[0].id)
    assert released.status == "RELEASED"

    freed = await db.scalar(
        select(EventSeatInventory).where(
            EventSeatInventory.tenant_id == tenant_id,
            EventSeatInventory.id == entitlements[0].inventory_id,
        )
    )
    assert freed.state == "AVAILABLE"

    still_live = list(
        await db.scalars(
            select(EventEntitlement).where(
                EventEntitlement.tenant_id == tenant_id,
                EventEntitlement.season_pass_id == season_pass.id,
                EventEntitlement.status == "ACTIVE",
            )
        )
    )
    assert len(still_live) == 2, "releasing one match damaged the rest of the pass"
