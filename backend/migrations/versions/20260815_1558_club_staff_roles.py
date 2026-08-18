"""club staff roles

Revision ID: f9b44764b0f4
Revises: 8a1eadb86839
Created: 2026-08-15 15:58:55.801952+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.rls import lift_force, restore_force

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
    # `team_staff` carries FORCE ROW LEVEL SECURITY, so as the migrator this
    # DELETE matches nothing — and the narrower constraint recreated below
    # would then reject the very rows it was meant to remove, blocking the
    # downgrade. See `lift_force`.
    for statement in lift_force(["team_staff"]):
        op.execute(statement)
    try:
        op.execute(
            "DELETE FROM team_staff WHERE role IN ('PRESS_OFFICER', 'PRESIDENT', 'DIRECTOR')"
        )
    finally:
        for statement in restore_force(["team_staff"]):
            op.execute(statement)
    op.execute("ALTER TABLE team_staff DROP CONSTRAINT ck_team_staff_team_staff_role_valid")
    op.execute(
        "ALTER TABLE team_staff ADD CONSTRAINT ck_team_staff_team_staff_role_valid "
        "CHECK (role IN ('HEAD_COACH', 'ASSISTANT_COACH', 'GOALKEEPING_COACH', 'FITNESS_COACH', 'ANALYST', 'PHYSIO', 'DOCTOR', 'TEAM_MANAGER', 'KIT_MANAGER'))"
    )
