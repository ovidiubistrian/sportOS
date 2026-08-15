"""audit partition function

Partition maintenance is DDL, and the runtime and platform roles deliberately
have no DDL rights — `app_migrator` owns the schema and nothing else may create
objects. Granting CREATE to the relay so it can add next month's partition
would dissolve that boundary for the sake of one statement.

Instead the migrator owns a `SECURITY DEFINER` function that creates exactly
one shape of object, derives the table name itself, and grants the runtime
roles access to the new partition. `app_platform` may execute it and nothing
else. Least privilege is preserved and the job works.

Revision ID: 5a7c2e918d64
Revises: 336b1da574fb
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "5a7c2e918d64"
down_revision: str | None = "336b1da574fb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREATE_FUNCTION = """
CREATE OR REPLACE FUNCTION create_audit_partition(p_month date)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
-- Pinned so the function cannot be redirected by a caller's search_path.
SET search_path = public, pg_temp
AS $$
DECLARE
    v_start date := date_trunc('month', p_month)::date;
    v_end   date := (date_trunc('month', p_month) + interval '1 month')::date;
    v_name  text := format('audit_log_%s', to_char(v_start, 'YYYY_MM'));
BEGIN
    -- The name is derived here, never supplied by the caller, so there is no
    -- injection surface even though this builds dynamic DDL.
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS %I PARTITION OF audit_log '
        'FOR VALUES FROM (%L) TO (%L)', v_name, v_start, v_end
    );
    EXECUTE format(
        'GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO app_runtime, app_platform',
        v_name
    );
    RETURN v_name;
END;
$$;
"""


def upgrade() -> None:
    op.execute(CREATE_FUNCTION)
    op.execute("REVOKE ALL ON FUNCTION create_audit_partition(date) FROM PUBLIC")
    op.execute(
        "GRANT EXECUTE ON FUNCTION create_audit_partition(date) TO app_platform"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS create_audit_partition(date)")
