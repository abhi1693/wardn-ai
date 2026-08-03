"""add workspace scheduled tasks

Revision ID: 202608040001
Revises: 202608020002
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202608040001"
down_revision: str | None = "202608020002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_scheduled_tasks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("last_task_run_id", sa.UUID(), nullable=True),
        sa.Column("last_agent_run_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("schedule_type", sa.String(length=32), nullable=False),
        sa.Column(
            "schedule_config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("timezone", sa.String(length=64), server_default="UTC", nullable=False),
        sa.Column(
            "output_routes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "conversation_policy",
            sa.String(length=32),
            server_default="reuse",
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=32), server_default="", nullable=False),
        sa.Column("last_error", sa.Text(), server_default="", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
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
            "schedule_type IN ('manual', 'interval', 'daily', 'weekly')",
            name="ck_workspace_scheduled_tasks_schedule_type",
        ),
        sa.CheckConstraint(
            "conversation_policy IN ('reuse', 'new_each_run')",
            name="ck_workspace_scheduled_tasks_conversation_policy",
        ),
        sa.CheckConstraint("btrim(name) <> ''", name="ck_workspace_scheduled_tasks_name"),
        sa.CheckConstraint(
            "btrim(instructions) <> ''",
            name="ck_workspace_scheduled_tasks_instructions",
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["workspace_conversations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["last_agent_run_id"],
            ["agent_runs.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_workspace_scheduled_tasks_agent_id",
        "workspace_scheduled_tasks",
        ["agent_id"],
    )
    op.create_index(
        "ix_workspace_scheduled_tasks_conversation_id",
        "workspace_scheduled_tasks",
        ["conversation_id"],
    )
    op.create_index(
        "ix_workspace_scheduled_tasks_created_by_id",
        "workspace_scheduled_tasks",
        ["created_by_id"],
    )
    op.create_index(
        "ix_workspace_scheduled_tasks_due",
        "workspace_scheduled_tasks",
        ["is_active", "next_run_at"],
    )
    op.create_index(
        "ix_workspace_scheduled_tasks_is_active",
        "workspace_scheduled_tasks",
        ["is_active"],
    )
    op.create_index(
        "ix_workspace_scheduled_tasks_last_agent_run_id",
        "workspace_scheduled_tasks",
        ["last_agent_run_id"],
    )
    op.create_index(
        "ix_workspace_scheduled_tasks_last_task_run_id",
        "workspace_scheduled_tasks",
        ["last_task_run_id"],
    )
    op.create_index(
        "ix_workspace_scheduled_tasks_next_run_at",
        "workspace_scheduled_tasks",
        ["next_run_at"],
    )
    op.create_index(
        "ix_workspace_scheduled_tasks_organization_id",
        "workspace_scheduled_tasks",
        ["organization_id"],
    )
    op.create_index(
        "ix_workspace_scheduled_tasks_schedule_type",
        "workspace_scheduled_tasks",
        ["schedule_type"],
    )
    op.create_index(
        "ix_workspace_scheduled_tasks_workspace_id",
        "workspace_scheduled_tasks",
        ["workspace_id"],
    )
    op.create_index(
        "uq_workspace_scheduled_tasks_workspace_name",
        "workspace_scheduled_tasks",
        ["workspace_id", "name"],
        unique=True,
    )

    op.create_table(
        "workspace_scheduled_task_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("agent_run_id", sa.UUID(), nullable=True),
        sa.Column("requested_by_id", sa.UUID(), nullable=True),
        sa.Column(
            "trigger_source",
            sa.String(length=32),
            server_default="scheduled",
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), server_default="queued", nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("worker_id", sa.String(length=255), server_default="", nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "delivery_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
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
            "status IN ('queued', 'running', 'succeeded', 'failed', 'waiting_confirmation')",
            name="ck_workspace_scheduled_task_runs_status",
        ),
        sa.CheckConstraint(
            "trigger_source IN ('scheduled', 'manual')",
            name="ck_workspace_scheduled_task_runs_trigger_source",
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["workspace_conversations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["workspace_scheduled_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_workspace_scheduled_task_runs_agent_id",
        "workspace_scheduled_task_runs",
        ["agent_id"],
    )
    op.create_index(
        "ix_workspace_scheduled_task_runs_agent_run_id",
        "workspace_scheduled_task_runs",
        ["agent_run_id"],
    )
    op.create_index(
        "ix_workspace_scheduled_task_runs_claimable",
        "workspace_scheduled_task_runs",
        ["status", "available_at"],
    )
    op.create_index(
        "ix_workspace_scheduled_task_runs_conversation_id",
        "workspace_scheduled_task_runs",
        ["conversation_id"],
    )
    op.create_index(
        "ix_workspace_scheduled_task_runs_organization_id",
        "workspace_scheduled_task_runs",
        ["organization_id"],
    )
    op.create_index(
        "ix_workspace_scheduled_task_runs_requested_by_id",
        "workspace_scheduled_task_runs",
        ["requested_by_id"],
    )
    op.create_index(
        "ix_workspace_scheduled_task_runs_status",
        "workspace_scheduled_task_runs",
        ["status"],
    )
    op.create_index(
        "ix_workspace_scheduled_task_runs_task_id",
        "workspace_scheduled_task_runs",
        ["task_id"],
    )
    op.create_index(
        "ix_workspace_scheduled_task_runs_task_scheduled",
        "workspace_scheduled_task_runs",
        ["task_id", "scheduled_for"],
    )
    op.create_index(
        "ix_workspace_scheduled_task_runs_workspace_id",
        "workspace_scheduled_task_runs",
        ["workspace_id"],
    )

    op.create_table(
        "workspace_scheduled_task_deliveries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("task_run_id", sa.UUID(), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=True),
        sa.Column("route_type", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=32), server_default="", nullable=False),
        sa.Column("external_thread_id", sa.String(length=255), server_default="", nullable=False),
        sa.Column("display_name", sa.String(length=255), server_default="", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), server_default="", nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
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
            "route_type IN ('chat', 'chat_provider')",
            name="ck_workspace_scheduled_task_deliveries_route_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'skipped')",
            name="ck_workspace_scheduled_task_deliveries_status",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["chat_provider_connections.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["workspace_scheduled_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["task_run_id"],
            ["workspace_scheduled_task_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_workspace_scheduled_task_deliveries_connection_id",
        "workspace_scheduled_task_deliveries",
        ["connection_id"],
    )
    op.create_index(
        "ix_workspace_scheduled_task_deliveries_organization_id",
        "workspace_scheduled_task_deliveries",
        ["organization_id"],
    )
    op.create_index(
        "ix_workspace_scheduled_task_deliveries_route_type",
        "workspace_scheduled_task_deliveries",
        ["route_type"],
    )
    op.create_index(
        "ix_workspace_scheduled_task_deliveries_status",
        "workspace_scheduled_task_deliveries",
        ["status"],
    )
    op.create_index(
        "ix_workspace_scheduled_task_deliveries_task_id",
        "workspace_scheduled_task_deliveries",
        ["task_id"],
    )
    op.create_index(
        "ix_workspace_scheduled_task_deliveries_task_run_id",
        "workspace_scheduled_task_deliveries",
        ["task_run_id"],
    )
    op.create_index(
        "ix_workspace_scheduled_task_deliveries_workspace_id",
        "workspace_scheduled_task_deliveries",
        ["workspace_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workspace_scheduled_task_deliveries_workspace_id",
        table_name="workspace_scheduled_task_deliveries",
    )
    op.drop_index(
        "ix_workspace_scheduled_task_deliveries_task_run_id",
        table_name="workspace_scheduled_task_deliveries",
    )
    op.drop_index(
        "ix_workspace_scheduled_task_deliveries_task_id",
        table_name="workspace_scheduled_task_deliveries",
    )
    op.drop_index(
        "ix_workspace_scheduled_task_deliveries_status",
        table_name="workspace_scheduled_task_deliveries",
    )
    op.drop_index(
        "ix_workspace_scheduled_task_deliveries_route_type",
        table_name="workspace_scheduled_task_deliveries",
    )
    op.drop_index(
        "ix_workspace_scheduled_task_deliveries_organization_id",
        table_name="workspace_scheduled_task_deliveries",
    )
    op.drop_index(
        "ix_workspace_scheduled_task_deliveries_connection_id",
        table_name="workspace_scheduled_task_deliveries",
    )
    op.drop_table("workspace_scheduled_task_deliveries")

    op.drop_index(
        "ix_workspace_scheduled_task_runs_workspace_id",
        table_name="workspace_scheduled_task_runs",
    )
    op.drop_index(
        "ix_workspace_scheduled_task_runs_task_scheduled",
        table_name="workspace_scheduled_task_runs",
    )
    op.drop_index(
        "ix_workspace_scheduled_task_runs_task_id",
        table_name="workspace_scheduled_task_runs",
    )
    op.drop_index(
        "ix_workspace_scheduled_task_runs_status",
        table_name="workspace_scheduled_task_runs",
    )
    op.drop_index(
        "ix_workspace_scheduled_task_runs_requested_by_id",
        table_name="workspace_scheduled_task_runs",
    )
    op.drop_index(
        "ix_workspace_scheduled_task_runs_organization_id",
        table_name="workspace_scheduled_task_runs",
    )
    op.drop_index(
        "ix_workspace_scheduled_task_runs_conversation_id",
        table_name="workspace_scheduled_task_runs",
    )
    op.drop_index(
        "ix_workspace_scheduled_task_runs_claimable",
        table_name="workspace_scheduled_task_runs",
    )
    op.drop_index(
        "ix_workspace_scheduled_task_runs_agent_run_id",
        table_name="workspace_scheduled_task_runs",
    )
    op.drop_index(
        "ix_workspace_scheduled_task_runs_agent_id",
        table_name="workspace_scheduled_task_runs",
    )
    op.drop_table("workspace_scheduled_task_runs")

    op.drop_index(
        "uq_workspace_scheduled_tasks_workspace_name",
        table_name="workspace_scheduled_tasks",
    )
    op.drop_index(
        "ix_workspace_scheduled_tasks_workspace_id",
        table_name="workspace_scheduled_tasks",
    )
    op.drop_index(
        "ix_workspace_scheduled_tasks_schedule_type",
        table_name="workspace_scheduled_tasks",
    )
    op.drop_index(
        "ix_workspace_scheduled_tasks_organization_id",
        table_name="workspace_scheduled_tasks",
    )
    op.drop_index(
        "ix_workspace_scheduled_tasks_next_run_at",
        table_name="workspace_scheduled_tasks",
    )
    op.drop_index(
        "ix_workspace_scheduled_tasks_last_task_run_id",
        table_name="workspace_scheduled_tasks",
    )
    op.drop_index(
        "ix_workspace_scheduled_tasks_last_agent_run_id",
        table_name="workspace_scheduled_tasks",
    )
    op.drop_index(
        "ix_workspace_scheduled_tasks_is_active",
        table_name="workspace_scheduled_tasks",
    )
    op.drop_index("ix_workspace_scheduled_tasks_due", table_name="workspace_scheduled_tasks")
    op.drop_index(
        "ix_workspace_scheduled_tasks_created_by_id",
        table_name="workspace_scheduled_tasks",
    )
    op.drop_index(
        "ix_workspace_scheduled_tasks_conversation_id",
        table_name="workspace_scheduled_tasks",
    )
    op.drop_index(
        "ix_workspace_scheduled_tasks_agent_id",
        table_name="workspace_scheduled_tasks",
    )
    op.drop_table("workspace_scheduled_tasks")
