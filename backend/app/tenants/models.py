from __future__ import annotations

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, GlobalModel, TenantScoped, Timestamped, UUIDPrimaryKey

TENANT_STATUSES = ("PENDING", "ACTIVE", "SUSPENDED", "CLOSED")
CLUB_STATUSES = ("ACTIVE", "ARCHIVED")


class Tenant(Base, UUIDPrimaryKey, Timestamped, GlobalModel):
    """The customer. Root of the ownership hierarchy.

    Not `TenantScoped` itself — it is the tenant. Its RLS policy restricts a
    request to the single row it is scoped to.
    """

    __tablename__ = "tenant"
    __table_args__ = (
        CheckConstraint("status IN " + str(TENANT_STATUSES), name="tenant_status_valid"),
        Index("ix_tenant_status", "status"),
    )

    slug: Mapped[str] = mapped_column(String(63), unique=True)
    legal_name: Mapped[str] = mapped_column(String(255))
    trading_name: Mapped[str | None] = mapped_column(String(255))

    country_code: Mapped[str] = mapped_column(String(2))
    default_locale: Mapped[str] = mapped_column(String(10), default="en")
    supported_locales: Mapped[list[str]] = mapped_column(ARRAY(String(10)), default=list)
    default_currency: Mapped[str] = mapped_column(String(3), default="EUR")
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    # Which sport this plays. See app/sports/registry.py — resolution is
    # team → club → tenant, so a single-sport club says it once and a CSM
    # running football and handball says it where it differs.
    sport: Mapped[str] = mapped_column(
        String(24), default="FOOTBALL", server_default="FOOTBALL"
    )


    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    suspended_reason: Mapped[str | None] = mapped_column(Text)

    vat_number: Mapped[str | None] = mapped_column(String(32))
    billing_email: Mapped[str | None] = mapped_column(CITEXT)

    # Marks seed data so it can never be mistaken for, or promoted to, real data.
    is_demo: Mapped[bool] = mapped_column(default=False)

    @property
    def is_operational(self) -> bool:
        return self.status == "ACTIVE"


class Club(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """A club within a tenant. Most tenants have one; nothing may assume it."""

    __tablename__ = "club"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_club_tenant_id_slug"),
        # Target for composite tenant foreign keys from child tables.
        UniqueConstraint("tenant_id", "id", name="uq_club_tenant_id_id"),
        CheckConstraint("status IN " + str(CLUB_STATUSES), name="club_status_valid"),
    )

    slug: Mapped[str] = mapped_column(String(63))
    legal_name: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255))
    short_name: Mapped[str] = mapped_column(String(8))

    founded_year: Mapped[int | None] = mapped_column()
    country_code: Mapped[str] = mapped_column(String(2))
    default_locale: Mapped[str] = mapped_column(String(10), default="en")
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    # Which sport this plays. See app/sports/registry.py — resolution is
    # team → club → tenant, so a single-sport club says it once and a CSM
    # running football and handball says it where it differs.
    sport: Mapped[str] = mapped_column(
        String(24), default="FOOTBALL", server_default="FOOTBALL"
    )

    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")

    # This club's entry in the platform club directory. Set the first time it
    # enters a competition — most clubs here are academies that never appear in
    # a fixture list, so it stays null until it means something. It is what
    # makes a fixture *belong* to this club rather than merely mention a name
    # that looks like it.
    directory_club_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    # Colours and template live in `club_branding`, so there is one source of
    # truth for how a club looks. See app/tenants/branding_models.py.


class ClubDomain(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """Hostname → club. The tenant-resolution key for the public site.

    `hostname` is globally unique: two tenants cannot claim the same domain,
    and an unknown host must 404 rather than fall back to a default club.
    """

    __tablename__ = "club_domain"
    __table_args__ = (
        UniqueConstraint("hostname", name="uq_club_domain_hostname"),
        Index("ix_club_domain_club", "tenant_id", "club_id"),
    )

    club_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("club.id", ondelete="CASCADE")
    )
    hostname: Mapped[str] = mapped_column(CITEXT)
    kind: Mapped[str] = mapped_column(String(16), default="PRIMARY")
    verification_status: Mapped[str] = mapped_column(String(16), default="VERIFIED")
