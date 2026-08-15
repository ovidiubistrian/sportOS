"""Reference data: permissions and system role templates.

Idempotent and safe to run on every deploy. The permission catalogue and role
templates are code (`app/authz/`); this projects them into the database so
roles can reference permissions with a foreign key.

Permissions removed from the catalogue are removed here too — a stale
permission row is a grant nobody can see in code review.
"""

from __future__ import annotations

import asyncio

import structlog
from sqlalchemy import delete, select

from app.authz.models import PermissionRecord, Role, RolePermission
from app.authz.permissions import CATALOGUE
from app.authz.role_templates import TEMPLATES
from app.authz.service import CACHE_PREFIX
from app.core.cache import cache
from app.core.db import platform_session
from app.core.logging import configure_logging

# Cross-module foreign keys can only resolve once every table is registered on
# the shared metadata. Any entrypoint that touches the ORM imports this.
from app.core import model_registry  # noqa: F401  isort: skip

log = structlog.get_logger("seed.reference")


async def seed_reference_data() -> None:
    async with platform_session(reason="seed reference data", routine=True) as session:
        existing = {
            row.key: row for row in await session.scalars(select(PermissionRecord))
        }
        catalogue_keys = {p.key for p in CATALOGUE}

        for permission in CATALOGUE:
            record = existing.get(permission.key)
            if record is None:
                session.add(
                    PermissionRecord(
                        key=permission.key,
                        module=permission.module,
                        description=permission.description,
                        is_sensitive=permission.is_sensitive,
                    )
                )
            else:
                record.module = permission.module
                record.description = permission.description
                record.is_sensitive = permission.is_sensitive

        removed = set(existing) - catalogue_keys
        if removed:
            log.warning("removing_stale_permissions", keys=sorted(removed))
            await session.execute(
                delete(PermissionRecord).where(PermissionRecord.key.in_(removed))
            )
        await session.flush()

        system_roles = {
            row.key: row
            for row in await session.scalars(
                select(Role).where(Role.tenant_id.is_(None), Role.is_system.is_(True))
            )
        }

        for template in TEMPLATES:
            role = system_roles.get(template.key)
            if role is None:
                role = Role(
                    tenant_id=None,
                    key=template.key,
                    name=template.name,
                    description=template.description,
                    scope_level=template.scope_level.name,
                    is_system=True,
                )
                session.add(role)
                await session.flush()
            else:
                role.name = template.name
                role.description = template.description
                role.scope_level = template.scope_level.name

            # Replace rather than merge: the template is the whole truth for a
            # system role, so a permission dropped from it is dropped here.
            await session.execute(
                delete(RolePermission).where(RolePermission.role_id == role.id)
            )
            for key in template.permissions:
                session.add(
                    RolePermission(role_id=role.id, permission_key=key)
                )

        log.info(
            "reference_data_seeded",
            permissions=len(CATALOGUE),
            roles=len(TEMPLATES),
        )

    # Effective permissions are cached per user behind a version counter, and
    # nothing here touches a user row — so without this a deploy that adds a
    # permission to a role appears to do nothing for up to a minute, and to
    # anyone debugging it, appears not to have worked at all.
    cleared = await cache.clear_prefix(CACHE_PREFIX)
    log.info("permission_cache_cleared", keys=cleared)


if __name__ == "__main__":
    configure_logging()
    asyncio.run(seed_reference_data())
