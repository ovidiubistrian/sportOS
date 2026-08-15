"""Tenant-scoped repository base.

Layer 2 of the isolation defence: every query built here is already filtered by
tenant, and every insert is already stamped. Domain code cannot forget, because
it never writes the filter.

Constructing a bare `select(SomeTenantScopedModel)` outside a repository is
blocked by `tests/isolation/test_raw_query_sweep.py`.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import current_tenant_id
from app.core.errors import NotFound
from app.core.models import Base, is_tenant_scoped


class TenantScopedRepository[ModelT: Base]:
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        if not is_tenant_scoped(self.model):
            raise TypeError(
                f"{self.model.__name__} is not tenant-scoped; "
                "use a plain repository for global models."
            )
        self.session = session

    @property
    def tenant_id(self) -> UUID:
        return current_tenant_id()

    def base_query(self) -> Select[tuple[ModelT]]:
        """The only sanctioned starting point for a query on this model."""
        return select(self.model).where(self.model.tenant_id == self.tenant_id)  # type: ignore[attr-defined]

    async def get(self, entity_id: UUID) -> ModelT | None:
        stmt = self.base_query().where(self.model.id == entity_id)  # type: ignore[attr-defined]
        return await self.session.scalar(stmt)

    async def get_or_404(self, entity_id: UUID) -> ModelT:
        entity = await self.get(entity_id)
        if entity is None:
            # 404 rather than 403: confirming existence would itself be a leak.
            raise NotFound(object_id=str(entity_id), object_type=self.model.__name__)
        return entity

    def add(self, entity: ModelT, **values: Any) -> ModelT:
        """Persist a new row, stamping the tenant from context."""
        entity.tenant_id = self.tenant_id  # type: ignore[attr-defined]
        for key, value in values.items():
            setattr(entity, key, value)
        self.session.add(entity)
        return entity

    async def delete(self, entity: ModelT) -> None:
        await self.session.delete(entity)
