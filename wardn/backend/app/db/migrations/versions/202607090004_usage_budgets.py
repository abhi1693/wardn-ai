"""add usage budgets

Revision ID: 202607090004
Revises: 202607090003
Create Date: 2026-07-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607090004"
down_revision: str | None = "202607090003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usage_budgets",
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("budget_key", sa.String(length=120), nullable=False),
        sa.Column("value", sa.Numeric(18, 10), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("period", sa.String(length=32), nullable=False),
        sa.Column("period_anchor", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model_filter", sa.String(length=255), server_default="", nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope_type",
            "scope_id",
            "budget_key",
            "model_filter",
            name="uq_usage_budgets_scope_key_model",
        ),
    )
    op.create_index(op.f("ix_usage_budgets_scope_type"), "usage_budgets", ["scope_type"])
    op.create_index(op.f("ix_usage_budgets_scope_id"), "usage_budgets", ["scope_id"])
    op.create_index(op.f("ix_usage_budgets_budget_key"), "usage_budgets", ["budget_key"])
    op.create_index(
        "ix_usage_budgets_scope_key",
        "usage_budgets",
        ["scope_type", "scope_id", "budget_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_usage_budgets_scope_key", table_name="usage_budgets")
    op.drop_index(op.f("ix_usage_budgets_budget_key"), table_name="usage_budgets")
    op.drop_index(op.f("ix_usage_budgets_scope_id"), table_name="usage_budgets")
    op.drop_index(op.f("ix_usage_budgets_scope_type"), table_name="usage_budgets")
    op.drop_table("usage_budgets")

