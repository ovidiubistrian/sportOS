"""encrypt stored gateway credentials

Revision ID: 14b57f215d2d
Revises: 5d0cd4541be4
Created: 2026-08-19 06:41:02.198534+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "14b57f215d2d"
down_revision: str | None = "5d0cd4541be4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

import json

from app.core.rls import lift_force, restore_force
from app.core.secrets import encrypt, is_encrypted


def upgrade() -> None:
    """Encrypt gateway passwords that were written before there was a key.

    A data migration on a tenant-scoped table, so the FORCE is lifted first —
    see `lift_force`. Without it this reports success and changes nothing,
    which for a migration whose whole purpose is to remove plaintext is the
    worst possible outcome.

    Rows already carrying the marker are skipped, so running this twice is
    harmless and a restore of a half-migrated backup finishes cleanly.
    """
    connection = op.get_bind()

    for statement in lift_force(["payment_credential"]):
        op.execute(statement)
    try:
        rows = connection.execute(
            sa.text("SELECT id, settings FROM payment_credential")
        ).fetchall()

        for row_id, settings in rows:
            settings = settings or {}
            password = settings.get("password") or ""
            if not password or is_encrypted(password):
                continue

            connection.execute(
                sa.text(
                    "UPDATE payment_credential SET settings = :settings WHERE id = :id"
                ).bindparams(
                    settings=json.dumps({**settings, "password": encrypt(password)}),
                    id=row_id,
                )
            )
    finally:
        for statement in restore_force(["payment_credential"]):
            op.execute(statement)


def downgrade() -> None:
    """Deliberately does nothing.

    Decrypting these back into the database would put plaintext credentials
    where this migration just removed them, to undo a change the application
    reads transparently either way — `decrypt` returns an unmarked value
    unchanged. A rollback of the code loses nothing by leaving them encrypted.
    """
