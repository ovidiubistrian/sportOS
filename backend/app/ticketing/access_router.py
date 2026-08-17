"""The access-control API — the contract the Android client will speak.

Six endpoints, exactly as specified. The browser scanner in the admin app uses
all of them today, so the mobile client will be a second consumer of a working
API rather than the first user of an untested one.

**Two ways in, deliberately.** A device authenticates with its own bearer token
(`X-Device-Token`) — a handset in a steward's hand has no Keycloak session and
should not have one. A signed-in operator with `ticketing.access.scan` can also
validate, which is what the browser demo and the box office use. Both land in
the same service and produce the same audited row.

**Rate limiting.** Validation is capped per device. A turnstile scans a few
times a second at most; a hundred a second is either a broken client retrying
or somebody working through a list of guessed codes, and both should be slowed
down rather than served.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import Db, Requires
from app.core.context import RequestContext
from app.core.errors import DomainError, NotFound
from app.ticketing import access_service
from app.ticketing.access_models import ScannerDevice

router = APIRouter(prefix="/access", tags=["access-control"])

SCAN = "ticketing.access.scan"
MANAGE = "ticketing.access.manage"

# A turnstile scans a few times a second. This is generous for a real gate and
# tight enough that walking a dictionary of references is not practical.
_RATE_LIMIT_PER_MINUTE = 240


class RateLimited(DomainError):
    code, status = "RATE_LIMITED", 429
    default_message = "Too many scans from this device. Slow down."


class EnrollIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    club_id: UUID
    name: str = Field(min_length=1, max_length=120)
    device_code: str = Field(min_length=1, max_length=32)
    platform: str | None = Field(default=None, max_length=32)


class EnrollOut(BaseModel):
    device_id: UUID
    device_code: str
    # Shown once and never again. A device that loses it enrols afresh.
    token: str
    expires_in_minutes: int


class ScanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    # Whatever the camera read, or what an operator typed off a printed ticket.
    credential: str = Field(min_length=1, max_length=200)
    gate_code: str | None = Field(default=None, max_length=24)
    scan_type: Literal["ENTRY", "EXIT"] = "ENTRY"
    # Required in practice: without one a dropped connection turns a retry into
    # ALREADY_USED against the device's own earlier success.
    idempotency_key: str | None = Field(default=None, max_length=64)
    operator_name: str | None = Field(default=None, max_length=160)
    scanned_at: datetime | None = None


class ScanOut(BaseModel):
    result: str
    scan_id: UUID | None = None
    ticket_number: str | None = None
    holder_name: str | None = None
    ticket_type: str | None = None
    seat: str | None = None
    gate_code: str | None = None
    scanned_at: datetime | None = None
    first_seen_at: datetime | None = None
    first_seen_gate: str | None = None


class SyncIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    scans: list[dict[str, Any]] = Field(max_length=500)


class GateAssignmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    gate_code: str = Field(min_length=1, max_length=24)


def _view(verdict: access_service.ScanVerdict) -> ScanOut:
    return ScanOut(
        result=verdict.result,
        scan_id=verdict.scan_id,
        ticket_number=verdict.ticket_number,
        holder_name=verdict.holder_name,
        ticket_type=verdict.ticket_type,
        seat=verdict.seat,
        gate_code=verdict.gate_code,
        scanned_at=verdict.scanned_at,
        first_seen_at=verdict.first_seen_at,
        first_seen_gate=verdict.first_seen_gate,
    )


async def _rate_limit(device: ScannerDevice | None, request: Request) -> None:
    """Cap scans per device per minute, in the shared cache.

    Fails open. A cache outage during a match must not stop a turnstile — the
    correctness guarantees are all in the database, and this is a throttle, not
    a control.
    """
    if device is None:
        return
    from app.core.cache import cache

    key = f"scanrate:{device.id}:{datetime.now(UTC).strftime('%Y%m%d%H%M')}"
    try:
        count = await cache.incr(key)
        # Set on every call rather than only the first: cheaper than a
        # round trip to find out whether the key is new, and the window is
        # fixed anyway.
        await cache.expire(key, 90)
    except Exception:
        return
    if count > _RATE_LIMIT_PER_MINUTE:
        raise RateLimited()


async def _device_from_header(
    db: Db, tenant_id: UUID, token: str | None
) -> ScannerDevice | None:
    if not token:
        return None
    return await access_service.device_for_token(db, tenant_id, token)


# --- device lifecycle -------------------------------------------------------


@router.post("/devices/enroll", response_model=EnrollOut, status_code=201)
async def enroll_device(
    payload: EnrollIn,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(MANAGE))],
) -> EnrollOut:
    """Register a scanner and issue its token. The token is shown once."""
    from app.core.config import settings

    device, token = await access_service.enroll_device(
        db,
        ctx.tenant,
        club_id=payload.club_id,
        name=payload.name,
        device_code=payload.device_code,
        platform=payload.platform,
        issued_by=ctx.actor_id,
    )
    return EnrollOut(
        device_id=device.id,
        device_code=device.device_code,
        token=token,
        expires_in_minutes=settings.scanner_token_minutes,
    )


@router.get("/devices", summary="Scanners")
async def list_devices(
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(MANAGE))],
) -> list[dict[str, Any]]:
    from sqlalchemy import select

    devices = await db.scalars(
        select(ScannerDevice)
        .where(ScannerDevice.tenant_id == ctx.tenant)
        .order_by(ScannerDevice.device_code)
    )
    return [
        {
            "id": str(d.id),
            "name": d.name,
            "device_code": d.device_code,
            "status": d.status,
            "platform": d.platform,
            "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
        }
        for d in devices
    ]


@router.get("/devices/{device_id}/config", summary="What a scanner needs at startup")
async def device_config(
    device_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(SCAN))],
) -> dict[str, Any]:
    return await access_service.device_config(db, ctx.tenant, device_id)


@router.post("/devices/{device_id}/revoke", summary="Stop a scanner working")
async def revoke_device(
    device_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(MANAGE))],
) -> dict[str, Any]:
    device = await access_service.revoke_device(db, ctx.tenant, device_id)
    return {"id": str(device.id), "status": device.status}


@router.post("/devices/{device_id}/gate", summary="Put a scanner on a gate")
async def assign_gate(
    device_id: UUID,
    payload: GateAssignmentIn,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(MANAGE))],
) -> dict[str, Any]:
    assignment = await access_service.assign_gate(
        db,
        ctx.tenant,
        device_id=device_id,
        event_id=payload.event_id,
        gate_code=payload.gate_code,
    )
    return {"id": str(assignment.id), "gate_code": assignment.gate_code}


# --- manifests and validation -----------------------------------------------


@router.get("/events/{event_id}/manifest", summary="The offline package for a gate")
async def event_manifest(
    event_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(SCAN))],
    gate_code: str | None = None,
) -> dict[str, Any]:
    return await access_service.event_manifest(db, ctx.tenant, event_id, gate_code=gate_code)


@router.post("/scans/validate", response_model=ScanOut, summary="Validate one ticket")
async def validate_scan(
    payload: ScanIn,
    request: Request,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(SCAN))],
    x_device_token: Annotated[str | None, Header(alias="X-Device-Token")] = None,
) -> ScanOut:
    device = await _device_from_header(db, ctx.tenant, x_device_token)
    await _rate_limit(device, request)

    verdict = await access_service.validate(
        db,
        ctx.tenant,
        event_id=payload.event_id,
        scanned=payload.credential,
        gate_code=payload.gate_code,
        device=device,
        idempotency_key=payload.idempotency_key,
        scan_type=payload.scan_type,
        operator_name=payload.operator_name,
        scanned_at=payload.scanned_at,
    )
    return _view(verdict)


@router.post("/scans/sync", summary="Flush a device's offline queue")
async def sync_scans(
    payload: SyncIn,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(SCAN))],
    x_device_token: Annotated[str | None, Header(alias="X-Device-Token")] = None,
) -> dict[str, Any]:
    device = await _device_from_header(db, ctx.tenant, x_device_token)
    verdicts = await access_service.sync_scans(
        db, ctx.tenant, event_id=payload.event_id, device=device, scans=payload.scans
    )
    return {
        "accepted": len(verdicts),
        "results": [_view(v).model_dump(mode="json") for v in verdicts],
    }


# --- control room -----------------------------------------------------------


@router.get("/events/{event_id}/live", summary="Who is inside, and what was refused")
async def live(
    event_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(SCAN))],
) -> dict[str, Any]:
    counts = await access_service.live_counts(db, ctx.tenant, event_id)
    counts["recent"] = await access_service.recent_scans(db, ctx.tenant, event_id)
    return counts


@router.get("/events/{event_id}/gates", summary="Gates in this match's snapshot")
async def event_gates(
    event_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(SCAN))],
) -> list[dict[str, Any]]:
    """Read from the snapshot, not the master.

    A steward's gate list must match the tickets that were sold, and those were
    priced and routed against the layout frozen at creation.
    """
    from app.ticketing.event_service import get_snapshot

    snapshot = await get_snapshot(db, ctx.tenant, event_id)
    gates = snapshot.payload.get("gates", [])
    if not gates:
        raise NotFound("This match's stadium snapshot has no gates.")
    return [
        {
            "code": gate["code"],
            "name": gate["name"],
            "kind": gate["kind"],
            "is_accessible": gate.get("is_accessible", False),
        }
        for gate in gates
    ]
