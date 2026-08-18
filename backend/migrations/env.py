from __future__ import annotations

import re
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.core.model_registry import *  # noqa: F403  registers all metadata
from app.core.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Migrations run as app_migrator, the schema owner. The runtime role has no DDL
# privileges at all, which is what makes "never modify production schemas
# manually" enforceable rather than aspirational.
config.set_main_option("sqlalchemy.url", settings.database_migrator_url)

target_metadata = Base.metadata

# Partitions are created at runtime by a maintenance job, so they exist in the
# database but never in the model metadata. Without this filter, every
# autogenerate proposes dropping them — which would delete audit history.
PARTITION_CHILD = re.compile(r"^(audit_log|ticket_scan)_\d{4}_\d{2}$")


def include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    if not reflected or not name:
        return True
    if type_ == "table" and PARTITION_CHILD.match(name):
        return False
    return not (
        type_ == "index" and PARTITION_CHILD.match(getattr(obj, "table", obj).name or "")
    )


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_migrator_url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        include_object=include_object,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
