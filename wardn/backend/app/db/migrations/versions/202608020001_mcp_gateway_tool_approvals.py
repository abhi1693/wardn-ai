"""add mcp gateway tool approvals

Revision ID: 202608020001
Revises: 202608010002
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202608020001"
down_revision: str | None = "202608010002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_gateway_tool_approvals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "organization_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("requested_by_id", sa.UUID(), nullable=True),
        sa.Column("decided_by_id", sa.UUID(), nullable=True),
        sa.Column("installation_id", sa.UUID(), nullable=False),
        sa.Column("tool_schema_id", sa.UUID(), nullable=True),
        sa.Column("tool_call_id", sa.String(length=255), nullable=False),
        sa.Column("server_name", sa.String(length=200), nullable=False),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column(
            "arguments",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "request_meta",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "guardrail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), server_default="", nullable=False),
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
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'denied')",
            name="ck_mcp_gateway_tool_approvals_status",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["installation_id"],
            ["mcp_server_installations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tool_schema_id"],
            ["mcp_server_tool_schemas.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mcp_gateway_tool_approvals_decided_by_id",
        "mcp_gateway_tool_approvals",
        ["decided_by_id"],
    )
    op.create_index(
        "ix_mcp_gateway_tool_approvals_installation_id",
        "mcp_gateway_tool_approvals",
        ["installation_id"],
    )
    op.create_index(
        "ix_mcp_gateway_tool_approvals_organization_id",
        "mcp_gateway_tool_approvals",
        ["organization_id"],
    )
    op.create_index(
        "ix_mcp_gateway_tool_approvals_requested_by_id",
        "mcp_gateway_tool_approvals",
        ["requested_by_id"],
    )
    op.create_index(
        "ix_mcp_gateway_tool_approvals_server_name",
        "mcp_gateway_tool_approvals",
        ["server_name"],
    )
    op.create_index(
        "ix_mcp_gateway_tool_approvals_status",
        "mcp_gateway_tool_approvals",
        ["status"],
    )
    op.create_index(
        "ix_mcp_gateway_tool_approvals_tool_call_id",
        "mcp_gateway_tool_approvals",
        ["tool_call_id"],
    )
    op.create_index(
        "ix_mcp_gateway_tool_approvals_tool_name",
        "mcp_gateway_tool_approvals",
        ["tool_name"],
    )
    op.create_index(
        "ix_mcp_gateway_tool_approvals_tool_schema_id",
        "mcp_gateway_tool_approvals",
        ["tool_schema_id"],
    )
    op.create_index(
        "ix_mcp_gateway_tool_approvals_workspace_id",
        "mcp_gateway_tool_approvals",
        ["workspace_id"],
    )
    op.create_index(
        "ix_mcp_gateway_tool_approvals_workspace_status_created",
        "mcp_gateway_tool_approvals",
        ["workspace_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mcp_gateway_tool_approvals_workspace_status_created",
        table_name="mcp_gateway_tool_approvals",
    )
    op.drop_index(
        "ix_mcp_gateway_tool_approvals_workspace_id",
        table_name="mcp_gateway_tool_approvals",
    )
    op.drop_index(
        "ix_mcp_gateway_tool_approvals_tool_schema_id",
        table_name="mcp_gateway_tool_approvals",
    )
    op.drop_index(
        "ix_mcp_gateway_tool_approvals_tool_name",
        table_name="mcp_gateway_tool_approvals",
    )
    op.drop_index(
        "ix_mcp_gateway_tool_approvals_tool_call_id",
        table_name="mcp_gateway_tool_approvals",
    )
    op.drop_index(
        "ix_mcp_gateway_tool_approvals_status",
        table_name="mcp_gateway_tool_approvals",
    )
    op.drop_index(
        "ix_mcp_gateway_tool_approvals_server_name",
        table_name="mcp_gateway_tool_approvals",
    )
    op.drop_index(
        "ix_mcp_gateway_tool_approvals_requested_by_id",
        table_name="mcp_gateway_tool_approvals",
    )
    op.drop_index(
        "ix_mcp_gateway_tool_approvals_organization_id",
        table_name="mcp_gateway_tool_approvals",
    )
    op.drop_index(
        "ix_mcp_gateway_tool_approvals_installation_id",
        table_name="mcp_gateway_tool_approvals",
    )
    op.drop_index(
        "ix_mcp_gateway_tool_approvals_decided_by_id",
        table_name="mcp_gateway_tool_approvals",
    )
    op.drop_table("mcp_gateway_tool_approvals")
