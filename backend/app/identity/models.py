from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, GlobalModel, TenantScoped, Timestamped, UUIDPrimaryKey

PERSON_SOURCES = ("STAFF_ENTRY", "SELF_REGISTRATION", "IMPORT", "DEMO")
ROLE_KINDS = ("PLAYER", "STAFF", "GUARDIAN", "FAN", "MEMBER", "PROSPECT")


class UserAccount(Base, UUIDPrimaryKey, Timestamped, GlobalModel):
    """An authentication identity. Mirrors Keycloak; never authoritative for auth.

    Global, not tenant-scoped: one login may be a person in several tenants
    (a supporter of two clubs). See ADR-0004.
    """

    __tablename__ = "user_account"
    __table_args__ = (
        UniqueConstraint("subject_id", name="uq_user_account_subject_id"),
        UniqueConstraint("email", name="uq_user_account_email"),
    )

    subject_id: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(CITEXT)
    email_verified: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    mfa_enabled: Mapped[bool] = mapped_column(default=False)
    is_platform_user: Mapped[bool] = mapped_column(default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Person(Base, UUIDPrimaryKey, Timestamped, TenantScoped):
    """A human being known to one tenant.

    Exists independently of whether they can log in: a U9 player and a
    supporter entered from a paper form are both people with no `user_id`.
    """

    __tablename__ = "person"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_person_tenant_id_id"),
        Index(
            "uq_person_tenant_user",
            "tenant_id",
            "user_id",
            unique=True,
            postgresql_where="user_id IS NOT NULL",
        ),
        Index("ix_person_name", "tenant_id", "last_name", "first_name"),
        Index("ix_person_email", "tenant_id", "email"),
        CheckConstraint("source IN " + str(PERSON_SOURCES), name="person_source_valid"),
    )

    user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user_account.id", ondelete="SET NULL")
    )

    first_name: Mapped[str] = mapped_column(String(120))
    last_name: Mapped[str] = mapped_column(String(120))
    display_name: Mapped[str] = mapped_column(String(255))

    birth_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    nationality: Mapped[list[str]] = mapped_column(ARRAY(String(2)), default=list)
    email: Mapped[str | None] = mapped_column(CITEXT)
    phone: Mapped[str | None] = mapped_column(String(32))
    preferred_locale: Mapped[str | None] = mapped_column(String(10))

    source: Mapped[str] = mapped_column(String(24), default="STAFF_ENTRY")
    # Erasure sets this and tombstones the identity fields; financial records
    # keep referencing the row. See docs/architecture/03-data-model.md §21.
    anonymized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def is_anonymized(self) -> bool:
        return self.anonymized_at is not None


class PersonRoleFlag(Base, Timestamped, TenantScoped):
    """Denormalised answer to "what is this person to us?".

    Asked on nearly every screen; without it that question is six LEFT JOINs.
    Maintained by the modules that create the attachments.
    """

    __tablename__ = "person_role_flag"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["person.tenant_id", "person.id"],
            name="fk_person_role_flag_person",
            ondelete="CASCADE",
        ),
        CheckConstraint("role_kind IN " + str(ROLE_KINDS), name="person_role_kind_valid"),
    )

    person_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    role_kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(  # type: ignore[assignment]
        PgUUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    is_active: Mapped[bool] = mapped_column(default=True)
