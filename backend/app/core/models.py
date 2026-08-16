"""Declarative base and the mixins that make tenancy structural.

A model either inherits `TenantScoped` or is explicitly registered as global.
`tests/isolation/test_model_sweep.py` enumerates every mapped class and fails
if one is neither — so a new tenant-scoped table without `tenant_id` cannot be
merged, rather than being caught in review if someone remembers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, MetaData, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from app.core.ids import new_id

# Deterministic constraint names, so migrations are reproducible and a
# constraint violation names something a human can find.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    # Fetch server-generated values with RETURNING on UPDATE as well as INSERT.
    # Without this, `updated_at` (a SQL `onupdate`) is expired after a flush,
    # and the next attribute read is a lazy SELECT — which on an async session
    # is not a slow query but a MissingGreenlet crash, in the response
    # serialiser, on every route that writes and then returns the object.
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    def __repr__(self) -> str:
        ident = getattr(self, "id", None)
        return f"<{type(self).__name__} {ident}>"


class UUIDPrimaryKey:
    @declared_attr.directive
    def id(cls) -> Mapped[UUID]:  # noqa: N805
        return mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_id)


class Timestamped:
    @declared_attr.directive
    def created_at(cls) -> Mapped[datetime]:  # noqa: N805
        return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    @declared_attr.directive
    def updated_at(cls) -> Mapped[datetime]:  # noqa: N805
        return mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        )


class TenantScoped:
    """Marks a table as belonging to exactly one tenant.

    Carries `tenant_id`, and signals to the migration tooling that this table
    needs an RLS policy and a `(tenant_id, id)` unique index for composite
    foreign keys from its children.
    """

    __tenant_scoped__ = True

    @declared_attr.directive
    def tenant_id(cls) -> Mapped[UUID]:  # noqa: N805
        return mapped_column(
            PgUUID(as_uuid=True),
            ForeignKey("tenant.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )


class GlobalModel:
    """Explicitly not tenant-scoped (plans, features, permissions, user accounts)."""

    __tenant_scoped__ = False


def is_tenant_scoped(model: type[Any]) -> bool:
    return bool(getattr(model, "__tenant_scoped__", False))


def tenant_scoped_tables() -> list[str]:
    return sorted(
        mapper.class_.__tablename__
        for mapper in Base.registry.mappers
        if is_tenant_scoped(mapper.class_)
    )
