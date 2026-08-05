"""add scheduled task notification rules and history

Revision ID: 202608050003
Revises: 202608050002
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202608050003"
down_revision: str | None = "202608050002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DEFAULT_NOTIFICATION_RULES = (
    """'{"on_failure": true, "on_waiting_approval": true, """
    """"on_no_output": false, "on_delivery_failure": true, """
    """"on_meaningful_update": false}'::jsonb"""
)


def upgrade() -> None:
    op.add_column(
        "workspace_scheduled_tasks",
        sa.Column(
            "notification_rules",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text(DEFAULT_NOTIFICATION_RULES),
            nullable=False,
        ),
    )
    op.add_column(
        "workspace_scheduled_tasks",
        sa.Column(
            "notification_routes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "workspace_scheduled_tasks",
        sa.Column(
            "approval_routes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "workspace_scheduled_tasks",
        sa.Column(
            "notification_state",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE workspace_scheduled_tasks
        SET notification_routes = CASE
                WHEN jsonb_typeof(output_routes) = 'array' AND jsonb_array_length(output_routes) > 0
                THEN output_routes
                ELSE '[{"route_type": "chat"}]'::jsonb
            END,
            approval_routes = CASE
                WHEN jsonb_typeof(output_routes) = 'array' AND jsonb_array_length(output_routes) > 0
                THEN output_routes
                ELSE '[{"route_type": "chat"}]'::jsonb
            END
        """
    )

    op.create_table(
        "workspace_scheduled_task_notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("route_type", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=32), server_default="", nullable=False),
        sa.Column("external_thread_id", sa.String(length=255), server_default="", nullable=False),
        sa.Column("display_name", sa.String(length=255), server_default="", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="sent", nullable=False),
        sa.Column("title", sa.String(length=255), server_default="", nullable=False),
        sa.Column("message", sa.Text(), server_default="", nullable=False),
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
            "event_type IN ('failure', 'waiting_approval', 'no_output', "
            "'delivery_failure', 'meaningful_update')",
            name="ck_workspace_scheduled_task_notifications_event_type",
        ),
        sa.CheckConstraint(
            "route_type IN ('chat', 'chat_provider')",
            name="ck_workspace_scheduled_task_notifications_route_type",
        ),
        sa.CheckConstraint(
            "status IN ('sent', 'failed', 'skipped')",
            name="ck_workspace_scheduled_task_notifications_status",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["chat_provider_connections.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["workspace_scheduled_tasks.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_run_id"],
            ["workspace_scheduled_task_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_workspace_scheduled_task_notifications_connection_id",
        "workspace_scheduled_task_notifications",
        ["connection_id"],
    )
    op.create_index(
        "ix_workspace_scheduled_task_notifications_event_type",
        "workspace_scheduled_task_notifications",
        ["event_type"],
    )
    op.create_index(
        "ix_workspace_scheduled_task_notifications_organization_id",
        "workspace_scheduled_task_notifications",
        ["organization_id"],
    )
    op.create_index(
        "ix_workspace_scheduled_task_notifications_route_type",
        "workspace_scheduled_task_notifications",
        ["route_type"],
    )
    op.create_index(
        "ix_workspace_scheduled_task_notifications_run_event",
        "workspace_scheduled_task_notifications",
        ["task_run_id", "event_type"],
    )
    op.create_index(
        "ix_workspace_scheduled_task_notifications_status",
        "workspace_scheduled_task_notifications",
        ["status"],
    )
    op.create_index(
        "ix_workspace_scheduled_task_notifications_task_id",
        "workspace_scheduled_task_notifications",
        ["task_id"],
    )
    op.create_index(
        "ix_workspace_scheduled_task_notifications_task_run_id",
        "workspace_scheduled_task_notifications",
        ["task_run_id"],
    )
    op.create_index(
        "ix_workspace_scheduled_task_notifications_workspace_id",
        "workspace_scheduled_task_notifications",
        ["workspace_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workspace_scheduled_task_notifications_workspace_id",
        table_name="workspace_scheduled_task_notifications",
    )
    op.drop_index(
        "ix_workspace_scheduled_task_notifications_task_run_id",
        table_name="workspace_scheduled_task_notifications",
    )
    op.drop_index(
        "ix_workspace_scheduled_task_notifications_task_id",
        table_name="workspace_scheduled_task_notifications",
    )
    op.drop_index(
        "ix_workspace_scheduled_task_notifications_status",
        table_name="workspace_scheduled_task_notifications",
    )
    op.drop_index(
        "ix_workspace_scheduled_task_notifications_run_event",
        table_name="workspace_scheduled_task_notifications",
    )
    op.drop_index(
        "ix_workspace_scheduled_task_notifications_route_type",
        table_name="workspace_scheduled_task_notifications",
    )
    op.drop_index(
        "ix_workspace_scheduled_task_notifications_organization_id",
        table_name="workspace_scheduled_task_notifications",
    )
    op.drop_index(
        "ix_workspace_scheduled_task_notifications_event_type",
        table_name="workspace_scheduled_task_notifications",
    )
    op.drop_index(
        "ix_workspace_scheduled_task_notifications_connection_id",
        table_name="workspace_scheduled_task_notifications",
    )
    op.drop_table("workspace_scheduled_task_notifications")
    op.drop_column("workspace_scheduled_tasks", "notification_state")
    op.drop_column("workspace_scheduled_tasks", "approval_routes")
    op.drop_column("workspace_scheduled_tasks", "notification_routes")
    op.drop_column("workspace_scheduled_tasks", "notification_rules")
