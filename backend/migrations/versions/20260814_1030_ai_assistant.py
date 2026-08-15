"""ai assistant: usage ledger and article types

Revision ID: 9b1f4c07ae52
Revises: 37a0dc6e78e0
Created: 2026-08-14 10:30:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.cms.article_types import ARTICLE_TYPES
from app.core.rls import disable, enable

revision: str = "9b1f4c07ae52"
down_revision: str | None = "37a0dc6e78e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AI_OPERATIONS = ("POLISH", "HEADLINES")


def upgrade() -> None:
    # --- article types on existing content --------------------------------
    # Everything written before types existed is an announcement; that is what
    # the type means by default, so no data is misdescribed by the backfill.
    op.add_column(
        "content_item",
        sa.Column(
            "article_type",
            sa.String(length=24),
            nullable=False,
            server_default="ANNOUNCEMENT",
        ),
    )
    # The default existed only so the backfill had a value. Dropping it puts
    # the choice back where it belongs — in the application, which validates it.
    op.alter_column("content_item", "article_type", server_default=None)
    op.create_check_constraint(
        "content_item_article_type_valid", "content_item", f"article_type IN {ARTICLE_TYPES}"
    )
    op.create_index(
        "ix_content_article_type", "content_item", ["tenant_id", "club_id", "article_type"]
    )

    # --- assistant usage ledger -------------------------------------------
    op.create_table(
        "ai_usage",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("club_id", sa.UUID(), nullable=True),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("operation", sa.String(length=24), nullable=False),
        sa.Column("object_type", sa.String(length=32), nullable=False),
        sa.Column("object_id", sa.UUID(), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("accepted", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(f"operation IN {AI_OPERATIONS}", name="ai_usage_operation_valid"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_usage_tenant_id", "ai_usage", ["tenant_id"])
    op.create_index("ix_ai_usage_tenant_period", "ai_usage", ["tenant_id", "created_at"])
    op.create_index("ix_ai_usage_platform", "ai_usage", ["created_at"])

    # The ledger holds no prompt text and no article content — only which
    # tenant asked for what, when, and how many tokens it cost. Drafts are
    # commercially sensitive (an unannounced signing is a story the club owns),
    # so nothing that could reconstruct one is stored here.
    for statement in enable("ai_usage"):
        op.execute(statement)

    # A tenant may read its own usage but must never rewrite the meter. The
    # service writes through the platform role, which is subject to the policy
    # only for the tenant it binds — writes happen with no tenant bound and are
    # allowed by the platform grant below.
    op.execute("GRANT SELECT ON ai_usage TO app_runtime")
    op.execute("GRANT SELECT, INSERT, UPDATE ON ai_usage TO app_platform")


def downgrade() -> None:
    for statement in disable("ai_usage"):
        op.execute(statement)
    op.drop_index("ix_ai_usage_platform", table_name="ai_usage")
    op.drop_index("ix_ai_usage_tenant_period", table_name="ai_usage")
    op.drop_index("ix_ai_usage_tenant_id", table_name="ai_usage")
    op.drop_table("ai_usage")

    op.drop_index("ix_content_article_type", table_name="content_item")
    op.drop_constraint("content_item_article_type_valid", "content_item", type_="check")
    op.drop_column("content_item", "article_type")
