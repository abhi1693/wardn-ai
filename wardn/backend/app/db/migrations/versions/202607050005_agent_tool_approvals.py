"""add agent tool approvals

Revision ID: 202607050005
Revises: 202607050004
Create Date: 2026-07-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607050005"
down_revision: str | None = "202607050004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_tool_approvals",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("requested_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("installation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_schema_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_call_id", sa.String(length=255), nullable=False),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
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
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_runs.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["workspace_conversations.id"],
            ondelete="SET NULL",
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
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["requested_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tool_schema_id"],
            ["mcp_server_tool_schemas.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_run_id",
            "tool_call_id",
            name="uq_agent_tool_approvals_run_tool_call",
        ),
    )
    op.create_index(
        op.f("ix_agent_tool_approvals_agent_id"),
        "agent_tool_approvals",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_tool_approvals_agent_run_id"),
        "agent_tool_approvals",
        ["agent_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_tool_approvals_conversation_id"),
        "agent_tool_approvals",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_tool_approvals_decided_by_id"),
        "agent_tool_approvals",
        ["decided_by_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_tool_approvals_installation_id"),
        "agent_tool_approvals",
        ["installation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_tool_approvals_organization_id"),
        "agent_tool_approvals",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_tool_approvals_requested_by_id"),
        "agent_tool_approvals",
        ["requested_by_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_tool_approvals_status"),
        "agent_tool_approvals",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_tool_approvals_tool_schema_id"),
        "agent_tool_approvals",
        ["tool_schema_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_tool_approvals_workspace_id"),
        "agent_tool_approvals",
        ["workspace_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_agent_tool_approvals_workspace_id"), table_name="agent_tool_approvals")
    op.drop_index(op.f("ix_agent_tool_approvals_tool_schema_id"), table_name="agent_tool_approvals")
    op.drop_index(op.f("ix_agent_tool_approvals_status"), table_name="agent_tool_approvals")
    op.drop_index(op.f("ix_agent_tool_approvals_requested_by_id"), table_name="agent_tool_approvals")
    op.drop_index(op.f("ix_agent_tool_approvals_organization_id"), table_name="agent_tool_approvals")
    op.drop_index(op.f("ix_agent_tool_approvals_installation_id"), table_name="agent_tool_approvals")
    op.drop_index(op.f("ix_agent_tool_approvals_decided_by_id"), table_name="agent_tool_approvals")
    op.drop_index(op.f("ix_agent_tool_approvals_conversation_id"), table_name="agent_tool_approvals")
    op.drop_index(op.f("ix_agent_tool_approvals_agent_run_id"), table_name="agent_tool_approvals")
    op.drop_index(op.f("ix_agent_tool_approvals_agent_id"), table_name="agent_tool_approvals")
    op.drop_table("agent_tool_approvals")
