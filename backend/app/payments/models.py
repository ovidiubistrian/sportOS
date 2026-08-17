"""What a tenant has configured, and what we said to the bank.

Two tables, both tenant-scoped. The first holds the credentials a club pasted
in; the second holds every call made with them.

On the credentials at rest: they are stored as they were given. The database is
the trust boundary here — the same one already holding every supporter's order
and email — and encrypting a column with a key that sits next to it in the same
environment buys very little. What it would buy is protection against a leaked
backup, which is worth having; `docs/architecture/09-payments.md` is where that
decision should be recorded when it is taken. Until then this is the honest
position rather than an accidental one.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantScoped, Timestamped, UUIDPrimaryKey

# Every provider the registry knows how to build. A key that is not here cannot
# be stored, so a typo in the settings screen fails at the write rather than
# silently leaving a club unable to take money.
PAYMENT_PROVIDERS = ("btipay",)


class PaymentCredential(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """One provider's credentials, for one tenant.

    Per tenant rather than per club: a gateway issues these against the legal
    entity that signed the processing contract, and a tenant running two clubs
    signed once.
    """

    __tablename__ = "payment_credential"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", name="uq_payment_credential"),
        UniqueConstraint("tenant_id", "id", name="uq_payment_credential_tenant_id_id"),
        CheckConstraint("provider IN " + str(PAYMENT_PROVIDERS), name="payment_provider_known"),
    )

    provider: Mapped[str] = mapped_column(String(24))
    # Shape is the provider's own. BT iPay: user_name, password, sandbox,
    # child_id. Read through the registry, never directly.
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    # A club can hold credentials without being open for business — while it
    # is still testing, or after it has asked us to stop taking card payments.
    is_live: Mapped[bool] = mapped_column(Boolean, default=False)

    updated_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))


class PaymentProviderCall(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """One call to a gateway: what was sent, what came back, how long it took.

    Kept for two reasons, and the second is the one that gets forgotten.

    The first is evidence. When a payment authenticates and the issuer then
    refuses it with a code nobody recognises, the club's argument with the bank
    is about what was submitted, and this is the record of it.

    The second is operational. This is the only place that remembers *every*
    order registered against a purchase. The order itself keeps a single
    payment reference, which the next attempt overwrites — so a buyer who
    presses pay twice and completes the first attempt comes back holding a
    reference that no longer matches anything. Without this table that payment
    is lost silently; with it, the return handler finds the purchase again.
    """

    __tablename__ = "payment_provider_call"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_payment_provider_call_tenant_id_id"),
        Index(
            "ix_payment_call_order",
            "tenant_id",
            "order_ref",
            "created_at",
        ),
        # How the return handler finds a purchase from a gateway's own id.
        Index("ix_payment_call_provider_order", "tenant_id", "provider_order_id"),
    )

    provider: Mapped[str] = mapped_column(String(24))
    # The gateway path, kept raw so calls can be grouped by what they did.
    endpoint: Mapped[str] = mapped_column(String(120))

    # Ours, and theirs. Both optional: a status call knows the gateway's id and
    # not ours, a failed registration the reverse.
    order_ref: Mapped[str | None] = mapped_column(String(64))
    provider_order_id: Mapped[str | None] = mapped_column(String(64))

    http_status: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(32))
    error_message: Mapped[str | None] = mapped_column(Text)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)

    # Verbatim apart from the secrets — see `app/payments/journal.py`. The
    # point of the record is that it is what was actually sent.
    sent: Mapped[dict] = mapped_column(JSONB, default=dict)
    received: Mapped[dict] = mapped_column(JSONB, default=dict)


class PaymentAttempt(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """A purchase's side of a payment: which order, which gateway session.

    The gateway's session id could live on the order itself, and in most
    systems it does — until the day a buyer pays on their second attempt and
    the column holds the third. A row per attempt keeps every session, so
    reconciliation can ask the gateway about all of them and confirm the one
    that was actually paid.
    """

    __tablename__ = "payment_attempt"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_payment_attempt_tenant_id_id"),
        UniqueConstraint(
            "tenant_id", "provider", "session_id", name="uq_payment_attempt_session"
        ),
        Index("ix_payment_attempt_order", "tenant_id", "order_id", "created_at"),
        # Reconciliation's sweep: attempts still open, oldest first.
        Index("ix_payment_attempt_open", "tenant_id", "settled_at"),
    )

    order_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    provider: Mapped[str] = mapped_column(String(24))
    session_id: Mapped[str] = mapped_column(String(64))
    amount_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))

    # Null while the outcome is unknown. Set once, when the gateway has told us
    # something final — which is what keeps reconciliation from asking about
    # the same dead session forever.
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(24), default="pending")
