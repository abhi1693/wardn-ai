"""Add cluster-wide repository metadata import rate limits.

Revision ID: 202607170003
Revises: 202607170002
Create Date: 2026-07-17 00:03:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607170003"
down_revision: str | None = "202607170002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_repository_metadata_rate_limits",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "window_started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("request_count", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "request_count > 0",
            name="ck_mcp_repository_metadata_rate_limits_request_count_positive",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("organization_id"),
    )


def downgrade() -> None:
    op.drop_table("mcp_repository_metadata_rate_limits")
