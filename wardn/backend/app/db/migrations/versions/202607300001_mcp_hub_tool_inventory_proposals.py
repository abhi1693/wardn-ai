"""Add deduped Hub tool inventory proposal tracking.

Revision ID: 202607300001
Revises: 202607260001
Create Date: 2026-07-30 00:01:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607300001"
down_revision: str | None = "202607260001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_hub_tool_inventory_proposals",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("installation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("server_name", sa.String(length=200), nullable=False),
        sa.Column("server_version", sa.String(length=255), nullable=False),
        sa.Column("hub_version_id", sa.String(length=36), nullable=False),
        sa.Column("inventory_hash", sa.String(length=64), nullable=False),
        sa.Column("tool_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("submission_id", sa.String(length=36), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('pending', 'submitted', 'failed', 'skipped')",
            name="ck_mcp_hub_tool_inventory_proposals_status",
        ),
        sa.ForeignKeyConstraint(
            ["installation_id"],
            ["mcp_server_installations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "hub_version_id",
            "inventory_hash",
            name="uq_mcp_hub_tool_inventory_proposals_version_hash",
        ),
    )
    op.create_index(
        op.f("ix_mcp_hub_tool_inventory_proposals_hub_version_id"),
        "mcp_hub_tool_inventory_proposals",
        ["hub_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_hub_tool_inventory_proposals_installation_id"),
        "mcp_hub_tool_inventory_proposals",
        ["installation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_hub_tool_inventory_proposals_organization_id"),
        "mcp_hub_tool_inventory_proposals",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_hub_tool_inventory_proposals_server_name"),
        "mcp_hub_tool_inventory_proposals",
        ["server_name"],
        unique=False,
    )
    op.create_index(
        "ix_mcp_hub_tool_inventory_proposals_server",
        "mcp_hub_tool_inventory_proposals",
        ["server_name", "server_version"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_hub_tool_inventory_proposals_server_version"),
        "mcp_hub_tool_inventory_proposals",
        ["server_version"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_hub_tool_inventory_proposals_status"),
        "mcp_hub_tool_inventory_proposals",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_hub_tool_inventory_proposals_workspace_id"),
        "mcp_hub_tool_inventory_proposals",
        ["workspace_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_mcp_hub_tool_inventory_proposals_workspace_id"),
        table_name="mcp_hub_tool_inventory_proposals",
    )
    op.drop_index(
        op.f("ix_mcp_hub_tool_inventory_proposals_status"),
        table_name="mcp_hub_tool_inventory_proposals",
    )
    op.drop_index(
        op.f("ix_mcp_hub_tool_inventory_proposals_server_version"),
        table_name="mcp_hub_tool_inventory_proposals",
    )
    op.drop_index(
        "ix_mcp_hub_tool_inventory_proposals_server",
        table_name="mcp_hub_tool_inventory_proposals",
    )
    op.drop_index(
        op.f("ix_mcp_hub_tool_inventory_proposals_server_name"),
        table_name="mcp_hub_tool_inventory_proposals",
    )
    op.drop_index(
        op.f("ix_mcp_hub_tool_inventory_proposals_organization_id"),
        table_name="mcp_hub_tool_inventory_proposals",
    )
    op.drop_index(
        op.f("ix_mcp_hub_tool_inventory_proposals_installation_id"),
        table_name="mcp_hub_tool_inventory_proposals",
    )
    op.drop_index(
        op.f("ix_mcp_hub_tool_inventory_proposals_hub_version_id"),
        table_name="mcp_hub_tool_inventory_proposals",
    )
    op.drop_table("mcp_hub_tool_inventory_proposals")
