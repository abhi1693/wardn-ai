"""Add MCP catalog sources.

Revision ID: 202606210012
Revises: 202606210011
Create Date: 2026-06-21 00:12:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202606210012"
down_revision: str | None = "202606210011"
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
        "mcp_catalog_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("base_url", sa.String(length=2048), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("sync_mode", sa.String(length=50), nullable=False, server_default="latest_only"),
        sa.Column(
            "secret_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_updated_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        timestamp_column("created_at"),
        timestamp_column("updated_at"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_mcp_catalog_sources_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "name",
            name="uq_mcp_catalog_sources_org_name",
        ),
    )
    op.create_index(
        "ix_mcp_catalog_sources_organization_id",
        "mcp_catalog_sources",
        ["organization_id"],
    )
    op.create_index("ix_mcp_catalog_sources_provider", "mcp_catalog_sources", ["provider"])
    op.create_index("ix_mcp_catalog_sources_is_enabled", "mcp_catalog_sources", ["is_enabled"])


def downgrade() -> None:
    op.drop_index("ix_mcp_catalog_sources_is_enabled", table_name="mcp_catalog_sources")
    op.drop_index("ix_mcp_catalog_sources_provider", table_name="mcp_catalog_sources")
    op.drop_index("ix_mcp_catalog_sources_organization_id", table_name="mcp_catalog_sources")
    op.drop_table("mcp_catalog_sources")
