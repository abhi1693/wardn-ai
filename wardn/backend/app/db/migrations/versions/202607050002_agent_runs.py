"""add agent runs

Revision ID: 202607050002
Revises: 202607050001
Create Date: 2026-07-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607050002"
down_revision: str | None = "202607050001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("triggered_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("trigger_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
            ["conversation_id"],
            ["workspace_conversations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["triggered_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_agent_runs_agent_id"), "agent_runs", ["agent_id"], unique=False)
    op.create_index(
        op.f("ix_agent_runs_conversation_id"),
        "agent_runs",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_runs_organization_id"),
        "agent_runs",
        ["organization_id"],
        unique=False,
    )
    op.create_index(op.f("ix_agent_runs_status"), "agent_runs", ["status"], unique=False)
    op.create_index(
        op.f("ix_agent_runs_triggered_by_id"),
        "agent_runs",
        ["triggered_by_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_runs_workspace_id"),
        "agent_runs",
        ["workspace_id"],
        unique=False,
    )

    op.add_column(
        "conversation_messages",
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_conversation_messages_agent_run_id_agent_runs",
        "conversation_messages",
        "agent_runs",
        ["agent_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_conversation_messages_agent_run_id"),
        "conversation_messages",
        ["agent_run_id"],
        unique=False,
    )

    op.create_table(
        "agent_run_steps",
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mcp_tool_invocation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("step_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
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
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["mcp_tool_invocation_id"],
            ["mcp_tool_invocations.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_run_id",
            "sequence",
            name="uq_agent_run_steps_run_sequence",
        ),
    )
    op.create_index(
        op.f("ix_agent_run_steps_agent_run_id"),
        "agent_run_steps",
        ["agent_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_run_steps_mcp_tool_invocation_id"),
        "agent_run_steps",
        ["mcp_tool_invocation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_run_steps_status"),
        "agent_run_steps",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_run_steps_step_type"),
        "agent_run_steps",
        ["step_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_agent_run_steps_step_type"), table_name="agent_run_steps")
    op.drop_index(op.f("ix_agent_run_steps_status"), table_name="agent_run_steps")
    op.drop_index(
        op.f("ix_agent_run_steps_mcp_tool_invocation_id"),
        table_name="agent_run_steps",
    )
    op.drop_index(op.f("ix_agent_run_steps_agent_run_id"), table_name="agent_run_steps")
    op.drop_table("agent_run_steps")
    op.drop_index(
        op.f("ix_conversation_messages_agent_run_id"),
        table_name="conversation_messages",
    )
    op.drop_constraint(
        "fk_conversation_messages_agent_run_id_agent_runs",
        "conversation_messages",
        type_="foreignkey",
    )
    op.drop_column("conversation_messages", "agent_run_id")
    op.drop_index(op.f("ix_agent_runs_workspace_id"), table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_triggered_by_id"), table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_status"), table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_organization_id"), table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_conversation_id"), table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_agent_id"), table_name="agent_runs")
    op.drop_table("agent_runs")
