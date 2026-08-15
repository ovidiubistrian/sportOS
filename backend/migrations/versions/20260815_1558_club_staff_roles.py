"""club staff roles

Revision ID: f9b44764b0f4
Revises: 8a1eadb86839
Created: 2026-08-15 15:58:55.801952+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "f9b44764b0f4"
down_revision: str | None = "8a1eadb86839"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A CHECK constraint's contents changing is invisible to autogenerate, so
    # the widened role list is written by hand. A club's press officer and its
    # president are staff a supporter expects to see named.
    op.execute("ALTER TABLE team_staff DROP CONSTRAINT ck_team_staff_team_staff_role_valid")
    op.execute(
        "ALTER TABLE team_staff ADD CONSTRAINT ck_team_staff_team_staff_role_valid "
        "CHECK (role IN ('HEAD_COACH', 'ASSISTANT_COACH', 'GOALKEEPING_COACH', 'FITNESS_COACH', 'ANALYST', 'PHYSIO', 'DOCTOR', 'TEAM_MANAGER', 'KIT_MANAGER', 'PRESS_OFFICER', 'PRESIDENT', 'DIRECTOR'))"
    )


def downgrade() -> None:
    op.execute("DELETE FROM team_staff WHERE role IN ('PRESS_OFFICER', 'PRESIDENT', 'DIRECTOR')")
    op.execute("ALTER TABLE team_staff DROP CONSTRAINT ck_team_staff_team_staff_role_valid")
    op.execute(
        "ALTER TABLE team_staff ADD CONSTRAINT ck_team_staff_team_staff_role_valid "
        "CHECK (role IN ('HEAD_COACH', 'ASSISTANT_COACH', 'GOALKEEPING_COACH', 'FITNESS_COACH', 'ANALYST', 'PHYSIO', 'DOCTOR', 'TEAM_MANAGER', 'KIT_MANAGER'))"
    )
