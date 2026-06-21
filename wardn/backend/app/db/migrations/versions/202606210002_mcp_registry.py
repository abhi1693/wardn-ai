"""mcp registry foundation

Revision ID: 202606210002
Revises: 202606210001
Create Date: 2026-06-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202606210002"
down_revision: str | None = "202606210001"
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
        "mcp_server_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("version", sa.String(length=255), nullable=False),
        sa.Column("website_url", sa.String(length=2048), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("status_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_latest", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("repository", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "packages",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "remotes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "icons",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("server_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "status_changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        timestamp_column("created_at"),
        timestamp_column("updated_at"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version", name="uq_mcp_server_versions_name_version"),
    )
    op.create_index("ix_mcp_server_versions_name", "mcp_server_versions", ["name"])
    op.create_index("ix_mcp_server_versions_status", "mcp_server_versions", ["status"])
    op.create_index("ix_mcp_server_versions_is_latest", "mcp_server_versions", ["is_latest"])


def downgrade() -> None:
    op.drop_index("ix_mcp_server_versions_is_latest", table_name="mcp_server_versions")
    op.drop_index("ix_mcp_server_versions_status", table_name="mcp_server_versions")
    op.drop_index("ix_mcp_server_versions_name", table_name="mcp_server_versions")
    op.drop_table("mcp_server_versions")
