"""mcp server installations

Revision ID: 202606210003
Revises: 202606210002
Create Date: 2026-06-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202606210003"
down_revision: str | None = "202606210002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamp_column(name: str) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "mcp_server_installations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("server_name", sa.String(length=200), nullable=False),
        sa.Column("installed_version", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="enabled"),
        sa.Column(
            "installed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        timestamp_column("created_at"),
        timestamp_column("updated_at"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_name", name="uq_mcp_server_installations_server_name"),
    )
    op.create_index(
        "ix_mcp_server_installations_server_name",
        "mcp_server_installations",
        ["server_name"],
    )
    op.create_index(
        "ix_mcp_server_installations_status",
        "mcp_server_installations",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_mcp_server_installations_status", table_name="mcp_server_installations")
    op.drop_index("ix_mcp_server_installations_server_name", table_name="mcp_server_installations")
    op.drop_table("mcp_server_installations")
