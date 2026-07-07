"""add resource limits

Revision ID: 202607070001
Revises: 202607050006
Create Date: 2026-07-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607070001"
down_revision: str | None = "202607050006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resource_limits",
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("limit_key", sa.String(length=120), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope_type",
            "scope_id",
            "limit_key",
            name="uq_resource_limits_scope_key",
        ),
    )
    op.create_index("ix_resource_limits_scope_type", "resource_limits", ["scope_type"])
    op.create_index("ix_resource_limits_scope_id", "resource_limits", ["scope_id"])
    op.create_index("ix_resource_limits_limit_key", "resource_limits", ["limit_key"])


def downgrade() -> None:
    op.drop_index("ix_resource_limits_limit_key", table_name="resource_limits")
    op.drop_index("ix_resource_limits_scope_id", table_name="resource_limits")
    op.drop_index("ix_resource_limits_scope_type", table_name="resource_limits")
    op.drop_table("resource_limits")
