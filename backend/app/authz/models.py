from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, GlobalModel, Timestamped, UUIDPrimaryKey

SCOPE_LEVELS = ("PLATFORM", "TENANT", "CLUB", "TEAM")


class PermissionRecord(Base, Timestamped, GlobalModel):
    """Seeded from `app/authz/permissions.py`. The catalogue is code; this is its
    projection, so roles can reference permissions with a foreign key."""

    __tablename__ = "permission"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    module: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text)
    is_sensitive: Mapped[bool] = mapped_column(default=False)


class Role(Base, UUIDPrimaryKey, Timestamped, GlobalModel):
    """A named bundle of permissions.

    `tenant_id IS NULL` marks a system template. Tenants may clone a template
    and edit the copy; they may never edit a template.

    Deliberately not `TenantScoped`: system templates have no tenant, and the
    table is read on every permission resolution including platform ones.
    """

    __tablename__ = "role"
    __table_args__ = (
        Index(
            "uq_role_tenant_key",
            "tenant_id",
            "key",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("scope_level IN " + str(SCOPE_LEVELS), name="role_scope_level_valid"),
    )

    tenant_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE")
    )
    key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    scope_level: Mapped[str] = mapped_column(String(16))
    is_system: Mapped[bool] = mapped_column(default=False)
    is_assignable: Mapped[bool] = mapped_column(default=True)


class RolePermission(Base, GlobalModel):
    __tablename__ = "role_permission"

    role_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("role.id", ondelete="CASCADE"), primary_key=True
    )
    permission_key: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("permission.key", ondelete="CASCADE"),
        primary_key=True,
    )


class RoleAssignment(Base, UUIDPrimaryKey, Timestamped, GlobalModel):
    """A user holds a role, narrowed to a scope.

    Global because a platform assignment has no tenant, and because resolution
    must read a user's assignments across tenants in one query at login.
    """

    __tablename__ = "role_assignment"
    __table_args__ = (
        Index(
            "ix_role_assignment_active",
            "user_id",
            "tenant_id",
            postgresql_where="revoked_at IS NULL",
        ),
        UniqueConstraint(
            "user_id",
            "role_id",
            "tenant_id",
            "club_id",
            "team_id",
            name="uq_role_assignment_unique_grant",
            postgresql_nulls_not_distinct=True,
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user_account.id", ondelete="CASCADE")
    )
    role_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("role.id", ondelete="RESTRICT")
    )

    tenant_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE")
    )
    club_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("club.id", ondelete="CASCADE")
    )
    team_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("team.id", ondelete="CASCADE")
    )

    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    granted_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(Text)
