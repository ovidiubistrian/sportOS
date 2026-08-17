"""Access control: the devices at the turnstiles and what they recorded.

The Android application is not built yet. These tables and the contracts in
`access_router.py` are what it will speak to, and the browser scanner in the
admin app already exercises every one of them — so the mobile client is a new
front end for a working system, not a new system.

**The one important design decision.** Single admission is a *database
constraint*, not application logic:

    UNIQUE (credential_id) WHERE result = 'VALID' AND scan_type = 'ENTRY'

A second scan of the same QR attempts an insert, violates the index, and the
service converts that violation into `ALREADY_USED` — which it then records as
its own non-VALID row. No locking, no read-then-write window, and correct under
any number of concurrent scanners or API replicas. Two stewards scanning the
same forged ticket at two gates in the same instant cannot both get a green
screen, because one of the two inserts must fail.

**What this cannot do.** Two devices that are both fully offline cannot detect a
duplicate between themselves — the constraint lives in a database neither can
reach. That is arithmetic, not a gap to be fixed later. ADR-0006 records the
mitigations (gate-partitioned manifests, frequent sync, post-match
reconciliation that flags every duplicate with gate, device and operator) and
requires the club to accept the residual risk in writing.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantScoped, Timestamped, UUIDPrimaryKey

DEVICE_STATUSES = ("PENDING", "ACTIVE", "REVOKED")

SCAN_TYPES = ("ENTRY", "EXIT")

# The machine-readable verdicts. The steward sees a colour and a word; the
# device logs the code; the reconciliation report groups by it. Strings rather
# than an integer enum so a log line is readable without a lookup table.
SCAN_RESULTS = (
    "VALID",
    "ALREADY_USED",
    "WRONG_GATE",
    "WRONG_EVENT",
    "NOT_YET_VALID",
    "EXPIRED",
    "CANCELLED",
    "REFUNDED",
    "DEVICE_REVOKED",
    "UNKNOWN_CREDENTIAL",
)

# Results that admitted somebody. Only these count towards attendance.
ADMITTING_RESULTS = ("VALID",)


class ScannerDevice(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """A handset or turnstile that may validate tickets for this club."""

    __tablename__ = "scanner_device"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_scanner_device_tenant_id_id"),
        UniqueConstraint("tenant_id", "device_code", name="uq_scanner_device_code"),
        CheckConstraint(
            "status IN " + str(DEVICE_STATUSES), name="scanner_device_status_valid"
        ),
        Index("ix_scanner_device_status", "tenant_id", "status"),
    )

    club_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))

    name: Mapped[str] = mapped_column(String(120))
    # What the steward reads off the back of the handset when calling the
    # control room: "scanner 4".
    device_code: Mapped[str] = mapped_column(String(32))
    platform: Mapped[str | None] = mapped_column(String(32))

    status: Mapped[str] = mapped_column(String(12), default="PENDING")

    enrolled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Updated on every call. A device that has not been seen since 14:00 on a
    # 15:00 kick-off is the control room's problem before the queue is.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    note: Mapped[str | None] = mapped_column(Text)


class DeviceEnrollment(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """A one-time code that turns into a device token.

    The token is stored **hashed**. A leaked database must not yield working
    scanner credentials, and nothing ever needs the original back — validation
    hashes what it is given and compares.

    Tokens are short-lived and re-issued at enrollment rather than being
    permanent secrets baked into the handset, so a lost device stops working on
    its own even if nobody remembers to revoke it.
    """

    __tablename__ = "device_enrollment"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "device_id"],
            ["scanner_device.tenant_id", "scanner_device.id"],
            name="fk_device_enrollment_device",
            ondelete="CASCADE",
        ),
        UniqueConstraint("enrollment_code", name="uq_device_enrollment_code"),
        UniqueConstraint("token_hash", name="uq_device_enrollment_token"),
        Index("ix_device_enrollment_device", "tenant_id", "device_id"),
    )

    device_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))

    enrollment_code: Mapped[str] = mapped_column(String(32))
    token_hash: Mapped[str] = mapped_column(String(64))

    issued_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GateAssignment(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """Which gate a device is working, for which match.

    Per event rather than permanent: the same handset is on Gate A for the
    league match and Gate D for the cup tie, and a wrong-gate verdict has to be
    right on both nights.
    """

    __tablename__ = "gate_assignment"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "device_id"],
            ["scanner_device.tenant_id", "scanner_device.id"],
            name="fk_gate_assignment_device",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["ticketed_event.tenant_id", "ticketed_event.id"],
            name="fk_gate_assignment_event",
            ondelete="CASCADE",
        ),
        UniqueConstraint("device_id", "event_id", name="uq_gate_assignment_device_event"),
        Index("ix_gate_assignment_event", "tenant_id", "event_id"),
    )

    device_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    event_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))

    # The gate *code*, not its row: the assignment is made against the event's
    # snapshot, and the master gate may not exist by the time somebody reads
    # the log next season.
    gate_code: Mapped[str] = mapped_column(String(24))

    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AccessRule(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """When a gate opens and what it admits, for one event.

    Absent a rule, a gate admits any credential whose sector it serves, from
    doors-open until kick-off plus an hour. The rule exists to narrow that: a
    VIP entrance that only takes VIP ticket types, an away turnstile that opens
    late, a media door with no public admission at all.
    """

    __tablename__ = "access_rule"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["ticketed_event.tenant_id", "ticketed_event.id"],
            name="fk_access_rule_event",
            ondelete="CASCADE",
        ),
        UniqueConstraint("event_id", "gate_code", name="uq_access_rule_gate"),
    )

    event_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    gate_code: Mapped[str] = mapped_column(String(24))

    opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Comma-separated ticket-type codes. Empty means "any".
    allowed_ticket_types: Mapped[str | None] = mapped_column(String(240))
    # ANY / HOME / AWAY, mirroring the gate's own setting but overridable per
    # event — segregation for a derby is not segregation for a friendly.
    supporter_side: Mapped[str] = mapped_column(String(8), default="ANY")

    # Whether somebody may leave and come back. See the module note: the single
    # admission constraint covers ENTRY scans, so allowing re-entry today means
    # the second entry is refused. Carried here so the rule is expressible and
    # the gap is visible, not silently ignored.
    allow_reentry: Mapped[bool] = mapped_column(default=False)

    note: Mapped[str | None] = mapped_column(Text)


class ScanLog(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """Every scan attempt, admitted or refused.

    Append-only. A refused scan is as important as an accepted one — 40
    ALREADY_USED verdicts at one gate is a forged batch, and the record is what
    proves it afterwards.
    """

    __tablename__ = "scan_log"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["ticketed_event.tenant_id", "ticketed_event.id"],
            name="fk_scan_log_event",
            ondelete="CASCADE",
        ),
        # ADR-0006. Single admission, enforced by the database rather than by
        # the service reading and then writing. Scoped to ENTRY so that an exit
        # scan does not consume the ticket.
        Index(
            "uq_scan_log_valid_entry",
            "credential_id",
            unique=True,
            postgresql_where=text("result = 'VALID' AND scan_type = 'ENTRY'"),
        ),
        # Retrying a scan the device already sent — after a timeout on a bad
        # connection — must not admit a second person or log a second entry.
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_scan_log_idempotency"),
        CheckConstraint("result IN " + str(SCAN_RESULTS), name="scan_log_result_valid"),
        CheckConstraint("scan_type IN " + str(SCAN_TYPES), name="scan_log_scan_type_valid"),
        Index("ix_scan_log_event_time", "tenant_id", "event_id", "server_at"),
        Index("ix_scan_log_gate", "tenant_id", "event_id", "gate_code", "result"),
    )

    event_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))

    # Null when the code was not recognised at all — there is nothing to point
    # at, and the attempt still has to be recorded.
    credential_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    # What was physically presented, kept even when unknown so a forged batch
    # can be recognised by its shape.
    presented_reference: Mapped[str | None] = mapped_column(String(64))

    device_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    gate_code: Mapped[str | None] = mapped_column(String(24))
    operator_name: Mapped[str | None] = mapped_column(String(160))

    scan_type: Mapped[str] = mapped_column(String(8), default="ENTRY")
    result: Mapped[str] = mapped_column(String(24))

    idempotency_key: Mapped[str] = mapped_column(String(64))

    # Two clocks, deliberately. The device's is what the steward saw; the
    # server's is what the audit trusts. A handset with a wrong clock — or a
    # deliberately altered one — must not be able to rewrite history.
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    server_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # True when the verdict was reached on the device without reaching the
    # server, and synced afterwards. Never a silent state: the steward sees a
    # persistent banner, and the reconciliation report separates these out.
    was_offline: Mapped[bool] = mapped_column(default=False)

    # Set when a later reconciliation found this scan duplicated another that
    # had been accepted offline elsewhere.
    duplicate_of_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    latency_ms: Mapped[int | None] = mapped_column(Integer)
    sequence: Mapped[int] = mapped_column(SmallInteger, default=0)
