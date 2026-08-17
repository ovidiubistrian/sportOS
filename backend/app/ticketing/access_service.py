"""Validating a scan, enrolling a device, and building an offline manifest.

The verdict order in `validate` is deliberate and worth stating, because it is
what the steward experiences. Cheap, certain refusals come first — an unknown
code, the wrong match, a revoked device — and the expensive, contended check
comes last. The final step is an *insert*, not a read:

    INSERT INTO scan_log (..., result = 'VALID', scan_type = 'ENTRY')

against `UNIQUE (credential_id) WHERE result = 'VALID' AND scan_type = 'ENTRY'`.
If the insert succeeds, this scanner admitted the holder and no other scanner
can. If it violates the index, somebody already came in on this ticket, and the
violation *is* the answer — converted to `ALREADY_USED` and itself recorded as
a separate row.

Doing it this way rather than "read, decide, write" removes the window where
two turnstiles both read `unused` and both admit. There is no window, because
there is no read.

**Idempotency.** Every request carries a key. A device that times out and
retries gets back the verdict it already earned rather than a second one —
otherwise a flaky connection turns one entry into an `ALREADY_USED` against its
own earlier success, and the steward turns away a supporter who did nothing
wrong.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import NotFound, ValidationFailed
from app.ticketing import credentials as credential_service
from app.ticketing.access_models import (
    AccessRule,
    DeviceEnrollment,
    GateAssignment,
    ScanLog,
    ScannerDevice,
)
from app.ticketing.event_models import EventSeatInventory, TicketedEvent
from app.ticketing.ticket_models import AccessCredential, EventEntitlement, Ticket

# How long after kick-off a gate keeps admitting, absent an explicit rule. A
# supporter arriving at half time is late, not a forgery.
DEFAULT_ADMISSION_GRACE = timedelta(hours=2)

# How early a gate opens, absent both a rule and a doors-open time.
DEFAULT_DOORS_BEFORE = timedelta(hours=2)


@dataclass(frozen=True, slots=True)
class ScanVerdict:
    """What the device shows the steward, and what the log records."""

    result: str
    scan_id: UUID | None = None
    ticket_number: str | None = None
    holder_name: str | None = None
    seat: str | None = None
    ticket_type: str | None = None
    gate_code: str | None = None
    scanned_at: datetime | None = None
    # Set on ALREADY_USED: when and where the first entry happened, which is
    # the first thing a steward is asked and the first thing they cannot
    # otherwise answer.
    first_seen_at: datetime | None = None
    first_seen_gate: str | None = None
    message: str | None = None

    @property
    def is_valid(self) -> bool:
        return self.result == "VALID"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def enroll_device(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    club_id: UUID,
    name: str,
    device_code: str,
    platform: str | None = None,
    issued_by: UUID | None = None,
) -> tuple[ScannerDevice, str]:
    """Register a scanner and hand back its token — once.

    The token is returned in plaintext here and stored only as a hash. There is
    no endpoint that reads it back: a device that loses its token is enrolled
    again, which is a deliberate cost. Anything that could re-display it would
    turn a database read into a working scanner.
    """
    existing = await session.scalar(
        select(ScannerDevice).where(
            ScannerDevice.tenant_id == tenant_id, ScannerDevice.device_code == device_code
        )
    )
    device = existing or ScannerDevice(
        tenant_id=tenant_id,
        club_id=club_id,
        name=name,
        device_code=device_code,
        platform=platform,
    )
    device.name = name
    device.platform = platform
    device.status = "ACTIVE"
    device.enrolled_at = datetime.now(UTC)
    device.revoked_at = None
    session.add(device)
    await session.flush()

    token = secrets.token_urlsafe(32)
    session.add(
        DeviceEnrollment(
            tenant_id=tenant_id,
            device_id=device.id,
            enrollment_code=secrets.token_urlsafe(9),
            token_hash=_hash_token(token),
            issued_by=issued_by,
            expires_at=datetime.now(UTC) + timedelta(minutes=settings.scanner_token_minutes),
            consumed_at=datetime.now(UTC),
        )
    )
    await session.flush()
    return device, token


async def device_for_token(
    session: AsyncSession, tenant_id: UUID, token: str
) -> ScannerDevice | None:
    """Resolve a bearer token to its device, if the token is still live."""
    enrollment = await session.scalar(
        select(DeviceEnrollment).where(
            DeviceEnrollment.tenant_id == tenant_id,
            DeviceEnrollment.token_hash == _hash_token(token),
            DeviceEnrollment.revoked_at.is_(None),
            DeviceEnrollment.expires_at > datetime.now(UTC),
        )
    )
    if enrollment is None:
        return None
    return await session.scalar(
        select(ScannerDevice).where(
            ScannerDevice.tenant_id == tenant_id, ScannerDevice.id == enrollment.device_id
        )
    )


async def revoke_device(
    session: AsyncSession, tenant_id: UUID, device_id: UUID
) -> ScannerDevice:
    """Stop a handset working, now.

    Revoking the device and every token it holds, rather than just the device
    row, so that a stolen scanner cannot keep validating on a cached token.
    """
    device = await session.scalar(
        select(ScannerDevice).where(
            ScannerDevice.tenant_id == tenant_id, ScannerDevice.id == device_id
        )
    )
    if device is None:
        raise NotFound("That scanner does not exist.")

    device.status = "REVOKED"
    device.revoked_at = datetime.now(UTC)
    for enrollment in await session.scalars(
        select(DeviceEnrollment).where(
            DeviceEnrollment.tenant_id == tenant_id,
            DeviceEnrollment.device_id == device_id,
            DeviceEnrollment.revoked_at.is_(None),
        )
    ):
        enrollment.revoked_at = datetime.now(UTC)
    await session.flush()
    return device


async def device_config(
    session: AsyncSession, tenant_id: UUID, device_id: UUID
) -> dict[str, Any]:
    """What a scanner needs to know about itself when it starts up."""
    device = await session.scalar(
        select(ScannerDevice).where(
            ScannerDevice.tenant_id == tenant_id, ScannerDevice.id == device_id
        )
    )
    if device is None:
        raise NotFound("That scanner does not exist.")

    assignments = list(
        await session.scalars(
            select(GateAssignment).where(
                GateAssignment.tenant_id == tenant_id, GateAssignment.device_id == device_id
            )
        )
    )
    return {
        "device_id": str(device.id),
        "name": device.name,
        "device_code": device.device_code,
        "status": device.status,
        # The scanner verifies signatures locally with this. Public by design.
        "signing_key_id": credential_service.key_id(),
        "public_key": credential_service.public_key_base64(),
        "assignments": [
            {
                "event_id": str(a.event_id),
                "gate_code": a.gate_code,
                "valid_from": a.valid_from.isoformat() if a.valid_from else None,
                "valid_until": a.valid_until.isoformat() if a.valid_until else None,
            }
            for a in assignments
        ],
    }


async def event_manifest(
    session: AsyncSession, tenant_id: UUID, event_id: UUID, *, gate_code: str | None = None
) -> dict[str, Any]:
    """The offline package for one event, optionally narrowed to one gate.

    **Gate-partitioned on purpose.** A credential valid only at Gate B is
    absent from Gate D's manifest, which shrinks both the download and the
    blast radius of a device being lost.

    Digests, not references. The manifest travels on a handset that may be
    stolen; a stolen list of SHA-256 digests admits nobody, whereas a list of
    live credential references is a book of working tickets.
    """
    event = await session.scalar(
        select(TicketedEvent).where(
            TicketedEvent.tenant_id == tenant_id, TicketedEvent.id == event_id
        )
    )
    if event is None:
        raise NotFound("That match does not exist.")

    query = select(AccessCredential).where(
        AccessCredential.tenant_id == tenant_id,
        AccessCredential.event_id == event_id,
        AccessCredential.status == "ACTIVE",
    )
    live = list(await session.scalars(query))

    entries = []
    for credential in live:
        if gate_code and credential.gate_codes:
            allowed = {c.strip() for c in credential.gate_codes.split(",") if c.strip()}
            if allowed and gate_code not in allowed:
                continue
        entries.append(
            {
                "digest": hashlib.sha256(credential.reference.encode()).hexdigest(),
                "section": credential.section_code,
                "gates": credential.gate_codes or "",
                "valid_from": credential.valid_from.isoformat()
                if credential.valid_from
                else None,
                "valid_until": credential.valid_until.isoformat()
                if credential.valid_until
                else None,
            }
        )

    revoked = [
        hashlib.sha256(reference.encode()).hexdigest()
        for reference in await session.scalars(
            select(AccessCredential.reference).where(
                AccessCredential.tenant_id == tenant_id,
                AccessCredential.event_id == event_id,
                AccessCredential.status.in_(("REVOKED", "SUPERSEDED")),
            )
        )
    ]

    return {
        "event_id": str(event_id),
        "event_name": event.name,
        "kickoff_at": event.kickoff_at.isoformat(),
        "gate_code": gate_code,
        "generated_at": datetime.now(UTC).isoformat(),
        "signing_key_id": credential_service.key_id(),
        "public_key": credential_service.public_key_base64(),
        "entries": entries,
        "revoked": revoked,
        # Stated in the payload, not only in the documentation, so a client
        # author cannot miss it. See ADR-0006.
        "offline_note": (
            "Two fully disconnected devices cannot detect a duplicate between "
            "themselves. Sync often and partition by gate."
        ),
    }


async def validate(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    event_id: UUID,
    scanned: str,
    gate_code: str | None,
    device: ScannerDevice | None = None,
    idempotency_key: str | None = None,
    scan_type: str = "ENTRY",
    operator_name: str | None = None,
    scanned_at: datetime | None = None,
    was_offline: bool = False,
) -> ScanVerdict:
    """Decide whether to open the turnstile, and record the decision."""
    now = datetime.now(UTC)
    key = idempotency_key or secrets.token_urlsafe(16)

    # A retry gets its original answer back. Checked first so that a repeat of
    # a successful scan never becomes ALREADY_USED against itself.
    previous = await session.scalar(
        select(ScanLog).where(ScanLog.tenant_id == tenant_id, ScanLog.idempotency_key == key)
    )
    if previous is not None:
        return await _verdict_from_log(session, tenant_id, previous)

    reference, _signature = credential_service.split_payload(scanned)
    if not reference:
        return await _record(
            session,
            tenant_id,
            event_id=event_id,
            result="UNKNOWN_CREDENTIAL",
            gate_code=gate_code,
            device=device,
            key=key,
            scan_type=scan_type,
            operator_name=operator_name,
            scanned_at=scanned_at,
            was_offline=was_offline,
            presented=scanned,
        )

    if device is not None and device.status == "REVOKED":
        return await _record(
            session,
            tenant_id,
            event_id=event_id,
            result="DEVICE_REVOKED",
            gate_code=gate_code,
            device=device,
            key=key,
            scan_type=scan_type,
            operator_name=operator_name,
            scanned_at=scanned_at,
            was_offline=was_offline,
            presented=reference,
        )

    credential = await session.scalar(
        select(AccessCredential).where(
            AccessCredential.tenant_id == tenant_id, AccessCredential.reference == reference
        )
    )
    if credential is None:
        return await _record(
            session,
            tenant_id,
            event_id=event_id,
            result="UNKNOWN_CREDENTIAL",
            gate_code=gate_code,
            device=device,
            key=key,
            scan_type=scan_type,
            operator_name=operator_name,
            scanned_at=scanned_at,
            was_offline=was_offline,
            presented=reference,
        )

    if credential.event_id != event_id:
        return await _record(
            session,
            tenant_id,
            event_id=event_id,
            result="WRONG_EVENT",
            gate_code=gate_code,
            device=device,
            key=key,
            scan_type=scan_type,
            operator_name=operator_name,
            scanned_at=scanned_at,
            was_offline=was_offline,
            presented=reference,
            credential=credential,
        )

    if credential.status != "ACTIVE":
        return await _record(
            session,
            tenant_id,
            event_id=event_id,
            result="CANCELLED",
            gate_code=gate_code,
            device=device,
            key=key,
            scan_type=scan_type,
            operator_name=operator_name,
            scanned_at=scanned_at,
            was_offline=was_offline,
            presented=reference,
            credential=credential,
        )

    ticket = await session.scalar(
        select(Ticket).where(Ticket.tenant_id == tenant_id, Ticket.id == credential.ticket_id)
    )
    entitlement = (
        await session.scalar(
            select(EventEntitlement).where(
                EventEntitlement.tenant_id == tenant_id,
                EventEntitlement.id == ticket.entitlement_id,
            )
        )
        if ticket
        else None
    )

    if ticket is None or entitlement is None:
        return await _record(
            session,
            tenant_id,
            event_id=event_id,
            result="UNKNOWN_CREDENTIAL",
            gate_code=gate_code,
            device=device,
            key=key,
            scan_type=scan_type,
            operator_name=operator_name,
            scanned_at=scanned_at,
            was_offline=was_offline,
            presented=reference,
            credential=credential,
        )

    if ticket.status == "REFUNDED" or entitlement.status == "REFUNDED":
        return await _record(
            session,
            tenant_id,
            event_id=event_id,
            result="REFUNDED",
            gate_code=gate_code,
            device=device,
            key=key,
            scan_type=scan_type,
            operator_name=operator_name,
            scanned_at=scanned_at,
            was_offline=was_offline,
            presented=reference,
            credential=credential,
            ticket=ticket,
        )
    dead = ("CANCELLED", "RELEASED", "TRANSFERRED")
    if ticket.status == "VOID" or entitlement.status in dead:
        return await _record(
            session,
            tenant_id,
            event_id=event_id,
            result="CANCELLED",
            gate_code=gate_code,
            device=device,
            key=key,
            scan_type=scan_type,
            operator_name=operator_name,
            scanned_at=scanned_at,
            was_offline=was_offline,
            presented=reference,
            credential=credential,
            ticket=ticket,
        )

    gate_result = await _check_gate(
        session, tenant_id, event_id=event_id, credential=credential, gate_code=gate_code
    )
    if gate_result is not None:
        return await _record(
            session,
            tenant_id,
            event_id=event_id,
            result=gate_result,
            gate_code=gate_code,
            device=device,
            key=key,
            scan_type=scan_type,
            operator_name=operator_name,
            scanned_at=scanned_at,
            was_offline=was_offline,
            presented=reference,
            credential=credential,
            ticket=ticket,
        )

    window = await _check_window(
        session,
        tenant_id,
        event_id=event_id,
        credential=credential,
        gate_code=gate_code,
        now=now,
    )
    if window is not None:
        return await _record(
            session,
            tenant_id,
            event_id=event_id,
            result=window,
            gate_code=gate_code,
            device=device,
            key=key,
            scan_type=scan_type,
            operator_name=operator_name,
            scanned_at=scanned_at,
            was_offline=was_offline,
            presented=reference,
            credential=credential,
            ticket=ticket,
        )

    # Everything cheap has passed. The admission itself is an insert against a
    # unique index — see the module docstring.
    return await _record(
        session,
        tenant_id,
        event_id=event_id,
        result="VALID",
        gate_code=gate_code,
        device=device,
        key=key,
        scan_type=scan_type,
        operator_name=operator_name,
        scanned_at=scanned_at,
        was_offline=was_offline,
        presented=reference,
        credential=credential,
        ticket=ticket,
    )


async def live_counts(session: AsyncSession, tenant_id: UUID, event_id: UUID) -> dict[str, Any]:
    """Who is inside, and what is being refused — the control-room view."""
    by_result = dict(
        (
            await session.execute(
                select(ScanLog.result, func.count())
                .where(ScanLog.tenant_id == tenant_id, ScanLog.event_id == event_id)
                .group_by(ScanLog.result)
            )
        ).all()
    )
    admitted = by_result.get("VALID", 0)

    by_gate = [
        {"gate_code": gate, "admitted": count}
        for gate, count in (
            await session.execute(
                select(ScanLog.gate_code, func.count())
                .where(
                    ScanLog.tenant_id == tenant_id,
                    ScanLog.event_id == event_id,
                    ScanLog.result == "VALID",
                    ScanLog.scan_type == "ENTRY",
                )
                .group_by(ScanLog.gate_code)
                .order_by(ScanLog.gate_code)
            )
        ).all()
    ]

    issued = await session.scalar(
        select(func.count())
        .select_from(Ticket)
        .where(
            Ticket.tenant_id == tenant_id,
            Ticket.event_id == event_id,
            Ticket.status == "ISSUED",
        )
    )
    return {
        "admitted": admitted,
        "issued": int(issued or 0),
        # Nobody who bought a ticket and did not come. Only meaningful once the
        # gates have closed, but cheap to compute and useful live.
        "no_shows": max(int(issued or 0) - admitted, 0),
        "refused": sum(count for result, count in by_result.items() if result != "VALID"),
        "by_result": by_result,
        "by_gate": by_gate,
    }


async def recent_scans(
    session: AsyncSession, tenant_id: UUID, event_id: UUID, *, limit: int = 20
) -> list[dict[str, Any]]:
    logs = list(
        await session.scalars(
            select(ScanLog)
            .where(ScanLog.tenant_id == tenant_id, ScanLog.event_id == event_id)
            .order_by(ScanLog.server_at.desc())
            .limit(limit)
        )
    )
    out = []
    for log in logs:
        seat = None
        if log.credential_id:
            seat = await _seat_label_for_credential(session, tenant_id, log.credential_id)
        out.append(
            {
                "id": str(log.id),
                "result": log.result,
                "gate_code": log.gate_code,
                "scan_type": log.scan_type,
                "server_at": log.server_at.isoformat(),
                "seat": seat,
                "was_offline": log.was_offline,
            }
        )
    return out


# --- internals -------------------------------------------------------------


async def _check_gate(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    event_id: UUID,
    credential: AccessCredential,
    gate_code: str | None,
) -> str | None:
    """`WRONG_GATE`, or None if this gate may admit this credential."""
    if not gate_code:
        return None

    if credential.gate_codes:
        allowed = {c.strip() for c in credential.gate_codes.split(",") if c.strip()}
        if allowed and gate_code not in allowed:
            return "WRONG_GATE"

    rule = await session.scalar(
        select(AccessRule).where(
            AccessRule.tenant_id == tenant_id,
            AccessRule.event_id == event_id,
            AccessRule.gate_code == gate_code,
        )
    )
    if rule is not None and rule.allowed_ticket_types:
        allowed_types = {t.strip() for t in rule.allowed_ticket_types.split(",") if t.strip()}
        ticket = await session.scalar(
            select(Ticket).where(
                Ticket.tenant_id == tenant_id, Ticket.id == credential.ticket_id
            )
        )
        wrong_type = ticket is not None and ticket.ticket_type_code not in allowed_types
        if allowed_types and wrong_type:
            return "WRONG_GATE"
    return None


async def _check_window(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    event_id: UUID,
    credential: AccessCredential,
    gate_code: str | None,
    now: datetime,
) -> str | None:
    """`NOT_YET_VALID`, `EXPIRED`, or None."""
    if credential.valid_from and now < credential.valid_from:
        return "NOT_YET_VALID"
    if credential.valid_until and now > credential.valid_until:
        return "EXPIRED"

    if gate_code:
        rule = await session.scalar(
            select(AccessRule).where(
                AccessRule.tenant_id == tenant_id,
                AccessRule.event_id == event_id,
                AccessRule.gate_code == gate_code,
            )
        )
        if rule is not None:
            if rule.opens_at and now < rule.opens_at:
                return "NOT_YET_VALID"
            if rule.closes_at and now > rule.closes_at:
                return "EXPIRED"
            return None

    event = await session.scalar(
        select(TicketedEvent).where(
            TicketedEvent.tenant_id == tenant_id, TicketedEvent.id == event_id
        )
    )
    if event is None:
        return None
    opens = event.doors_open_at or (event.kickoff_at - DEFAULT_DOORS_BEFORE)
    if now < opens:
        return "NOT_YET_VALID"
    if now > event.kickoff_at + DEFAULT_ADMISSION_GRACE:
        return "EXPIRED"
    return None


async def _record(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    event_id: UUID,
    result: str,
    gate_code: str | None,
    device: ScannerDevice | None,
    key: str,
    scan_type: str,
    operator_name: str | None,
    scanned_at: datetime | None,
    was_offline: bool,
    presented: str | None = None,
    credential: AccessCredential | None = None,
    ticket: Ticket | None = None,
) -> ScanVerdict:
    """Write the scan, converting a unique violation into ALREADY_USED.

    The savepoint matters: a failed insert marks the surrounding transaction
    unusable in Postgres, and everything after this — including writing the
    ALREADY_USED row itself — happens in that same transaction.
    """
    now = datetime.now(UTC)
    if device is not None:
        device.last_seen_at = now

    log = ScanLog(
        tenant_id=tenant_id,
        event_id=event_id,
        credential_id=credential.id if credential else None,
        presented_reference=(presented or "")[:64] or None,
        device_id=device.id if device else None,
        gate_code=gate_code,
        operator_name=operator_name,
        scan_type=scan_type,
        result=result,
        idempotency_key=key,
        scanned_at=scanned_at,
        server_at=now,
        was_offline=was_offline,
    )

    try:
        async with session.begin_nested():
            session.add(log)
            await session.flush()
    except IntegrityError:
        if result != "VALID" or credential is None:
            raise

        first = await session.scalar(
            select(ScanLog).where(
                ScanLog.tenant_id == tenant_id,
                ScanLog.credential_id == credential.id,
                ScanLog.result == "VALID",
                ScanLog.scan_type == "ENTRY",
            )
        )
        duplicate = ScanLog(
            tenant_id=tenant_id,
            event_id=event_id,
            credential_id=credential.id,
            presented_reference=(presented or "")[:64] or None,
            device_id=device.id if device else None,
            gate_code=gate_code,
            operator_name=operator_name,
            scan_type=scan_type,
            result="ALREADY_USED",
            idempotency_key=key,
            scanned_at=scanned_at,
            server_at=now,
            was_offline=was_offline,
            duplicate_of_id=first.id if first else None,
        )
        session.add(duplicate)
        await session.flush()
        return await _verdict_from_log(
            session, tenant_id, duplicate, ticket=ticket, first=first
        )

    return await _verdict_from_log(session, tenant_id, log, ticket=ticket)


async def _verdict_from_log(
    session: AsyncSession,
    tenant_id: UUID,
    log: ScanLog,
    *,
    ticket: Ticket | None = None,
    first: ScanLog | None = None,
) -> ScanVerdict:
    if ticket is None and log.credential_id is not None:
        credential = await session.scalar(
            select(AccessCredential).where(
                AccessCredential.tenant_id == tenant_id,
                AccessCredential.id == log.credential_id,
            )
        )
        if credential is not None:
            ticket = await session.scalar(
                select(Ticket).where(
                    Ticket.tenant_id == tenant_id, Ticket.id == credential.ticket_id
                )
            )

    if first is None and log.result == "ALREADY_USED" and log.credential_id is not None:
        first = await session.scalar(
            select(ScanLog).where(
                ScanLog.tenant_id == tenant_id,
                ScanLog.credential_id == log.credential_id,
                ScanLog.result == "VALID",
                ScanLog.scan_type == "ENTRY",
            )
        )

    seat = (
        await _seat_label_for_credential(session, tenant_id, log.credential_id)
        if log.credential_id
        else None
    )

    return ScanVerdict(
        result=log.result,
        scan_id=log.id,
        ticket_number=ticket.ticket_number if ticket else None,
        holder_name=ticket.holder_name if ticket else None,
        ticket_type=ticket.ticket_type_name if ticket else None,
        seat=seat,
        gate_code=log.gate_code,
        scanned_at=log.server_at,
        first_seen_at=first.server_at if first else None,
        first_seen_gate=first.gate_code if first else None,
    )


async def _seat_label_for_credential(
    session: AsyncSession, tenant_id: UUID, credential_id: UUID
) -> str | None:
    """The human seat description, read from the event's own inventory."""
    credential = await session.scalar(
        select(AccessCredential).where(
            AccessCredential.tenant_id == tenant_id, AccessCredential.id == credential_id
        )
    )
    if credential is None:
        return None
    ticket = await session.scalar(
        select(Ticket).where(Ticket.tenant_id == tenant_id, Ticket.id == credential.ticket_id)
    )
    if ticket is None:
        return None
    entitlement = await session.scalar(
        select(EventEntitlement).where(
            EventEntitlement.tenant_id == tenant_id,
            EventEntitlement.id == ticket.entitlement_id,
        )
    )
    if entitlement is None:
        return None
    row = await session.scalar(
        select(EventSeatInventory).where(
            EventSeatInventory.tenant_id == tenant_id,
            EventSeatInventory.id == entitlement.inventory_id,
        )
    )
    if row is None:
        return None
    if row.seat_label is None:
        return f"{row.stand_name} · {row.section_name}"
    return f"{row.stand_name} · {row.section_name} · {row.row_label}{row.seat_label}"


async def assign_gate(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    device_id: UUID,
    event_id: UUID,
    gate_code: str,
) -> GateAssignment:
    existing = await session.scalar(
        select(GateAssignment).where(
            GateAssignment.tenant_id == tenant_id,
            GateAssignment.device_id == device_id,
            GateAssignment.event_id == event_id,
        )
    )
    if existing is not None:
        existing.gate_code = gate_code
        await session.flush()
        return existing

    assignment = GateAssignment(
        tenant_id=tenant_id, device_id=device_id, event_id=event_id, gate_code=gate_code
    )
    session.add(assignment)
    await session.flush()
    return assignment


async def sync_scans(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    event_id: UUID,
    device: ScannerDevice | None,
    scans: list[dict[str, Any]],
) -> list[ScanVerdict]:
    """Flush a device's offline queue.

    Each entry is replayed through `validate` with its own idempotency key, so
    a batch sent twice — which happens when a connection drops mid-flush — does
    not admit anybody twice or invent duplicate refusals.
    """
    if len(scans) > 500:
        raise ValidationFailed("Sync at most 500 scans at a time.", field="scans")

    verdicts = []
    for entry in scans:
        verdicts.append(
            await validate(
                session,
                tenant_id,
                event_id=event_id,
                scanned=str(entry.get("credential") or ""),
                gate_code=entry.get("gate_code"),
                device=device,
                idempotency_key=str(entry.get("idempotency_key") or ""),
                scan_type=str(entry.get("scan_type") or "ENTRY"),
                operator_name=entry.get("operator_name"),
                scanned_at=_parse_time(entry.get("scanned_at")),
                was_offline=True,
            )
        )
    return verdicts


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
