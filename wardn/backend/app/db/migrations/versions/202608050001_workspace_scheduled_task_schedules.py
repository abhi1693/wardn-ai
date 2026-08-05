"""add owned scheduled task schedules

Revision ID: 202608050001
Revises: 202608040001
Create Date: 2026-08-05
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202608050001"
down_revision: str | None = "202608040001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_workspace_scheduled_tasks_schedule_type",
        "workspace_scheduled_tasks",
        type_="check",
    )
    op.create_check_constraint(
        "ck_workspace_scheduled_tasks_schedule_type",
        "workspace_scheduled_tasks",
        (
            "schedule_type IN ("
            "'manual', 'interval', 'daily', 'weekly', 'weekdays', 'monthly', "
            "'cron', 'multiple'"
            ")"
        ),
    )

    op.create_table(
        "workspace_scheduled_task_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), server_default="", nullable=False),
        sa.Column("schedule_type", sa.String(length=32), nullable=False),
        sa.Column(
            "schedule_config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("timezone", sa.String(length=64), server_default="UTC", nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
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
            "schedule_type IN ('interval', 'daily', 'weekly', 'weekdays', 'monthly', 'cron')",
            name="ck_workspace_scheduled_task_schedules_schedule_type",
        ),
        sa.CheckConstraint(
            "sort_order >= 0",
            name="ck_workspace_scheduled_task_schedules_sort_order",
        ),
        sa.CheckConstraint(
            "(starts_at IS NULL OR ends_at IS NULL OR ends_at > starts_at)",
            name="ck_workspace_scheduled_task_schedules_window",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["workspace_scheduled_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_workspace_scheduled_task_schedules_due",
        "workspace_scheduled_task_schedules",
        ["is_active", "next_run_at"],
    )
    op.create_index(
        "ix_workspace_scheduled_task_schedules_is_active",
        "workspace_scheduled_task_schedules",
        ["is_active"],
    )
    op.create_index(
        "ix_workspace_scheduled_task_schedules_next_run_at",
        "workspace_scheduled_task_schedules",
        ["next_run_at"],
    )
    op.create_index(
        "ix_workspace_scheduled_task_schedules_organization_id",
        "workspace_scheduled_task_schedules",
        ["organization_id"],
    )
    op.create_index(
        "ix_workspace_scheduled_task_schedules_schedule_type",
        "workspace_scheduled_task_schedules",
        ["schedule_type"],
    )
    op.create_index(
        "ix_workspace_scheduled_task_schedules_task_id",
        "workspace_scheduled_task_schedules",
        ["task_id"],
    )
    op.create_index(
        "ix_workspace_scheduled_task_schedules_task_order",
        "workspace_scheduled_task_schedules",
        ["task_id", "sort_order"],
    )
    op.create_index(
        "ix_workspace_scheduled_task_schedules_workspace_id",
        "workspace_scheduled_task_schedules",
        ["workspace_id"],
    )

    connection = op.get_bind()
    schedule_rows = []
    result = connection.execute(
        sa.text(
            """
            SELECT id, organization_id, workspace_id, schedule_type, schedule_config,
                   timezone, is_active, next_run_at, created_at, updated_at
            FROM workspace_scheduled_tasks
            WHERE schedule_type IN ('interval', 'daily', 'weekly')
            """
        )
    )
    for task in result.mappings():
        schedule_rows.append(
            {
                "id": uuid4(),
                "organization_id": task["organization_id"],
                "workspace_id": task["workspace_id"],
                "task_id": task["id"],
                "name": "",
                "schedule_type": task["schedule_type"],
                "schedule_config": task["schedule_config"] or {},
                "timezone": task["timezone"] or "UTC",
                "starts_at": None,
                "ends_at": None,
                "is_active": task["is_active"],
                "sort_order": 0,
                "next_run_at": task["next_run_at"] if task["is_active"] else None,
                "created_at": task["created_at"],
                "updated_at": task["updated_at"],
            }
        )

    if schedule_rows:
        schedule_table = sa.table(
            "workspace_scheduled_task_schedules",
            sa.column("id", postgresql.UUID(as_uuid=True)),
            sa.column("organization_id", postgresql.UUID(as_uuid=True)),
            sa.column("workspace_id", postgresql.UUID(as_uuid=True)),
            sa.column("task_id", postgresql.UUID(as_uuid=True)),
            sa.column("name", sa.String(length=120)),
            sa.column("schedule_type", sa.String(length=32)),
            sa.column("schedule_config", postgresql.JSONB(astext_type=sa.Text())),
            sa.column("timezone", sa.String(length=64)),
            sa.column("starts_at", sa.DateTime(timezone=True)),
            sa.column("ends_at", sa.DateTime(timezone=True)),
            sa.column("is_active", sa.Boolean()),
            sa.column("sort_order", sa.Integer()),
            sa.column("next_run_at", sa.DateTime(timezone=True)),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        )
        connection.execute(schedule_table.insert(), schedule_rows)

    op.add_column(
        "workspace_scheduled_task_runs",
        sa.Column("task_schedule_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_workspace_scheduled_task_runs_task_schedule_id",
        "workspace_scheduled_task_runs",
        "workspace_scheduled_task_schedules",
        ["task_schedule_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_workspace_scheduled_task_runs_task_schedule_id",
        "workspace_scheduled_task_runs",
        ["task_schedule_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workspace_scheduled_task_runs_task_schedule_id",
        table_name="workspace_scheduled_task_runs",
    )
    op.drop_constraint(
        "fk_workspace_scheduled_task_runs_task_schedule_id",
        "workspace_scheduled_task_runs",
        type_="foreignkey",
    )
    op.drop_column("workspace_scheduled_task_runs", "task_schedule_id")

    op.drop_index(
        "ix_workspace_scheduled_task_schedules_workspace_id",
        table_name="workspace_scheduled_task_schedules",
    )
    op.drop_index(
        "ix_workspace_scheduled_task_schedules_task_order",
        table_name="workspace_scheduled_task_schedules",
    )
    op.drop_index(
        "ix_workspace_scheduled_task_schedules_task_id",
        table_name="workspace_scheduled_task_schedules",
    )
    op.drop_index(
        "ix_workspace_scheduled_task_schedules_schedule_type",
        table_name="workspace_scheduled_task_schedules",
    )
    op.drop_index(
        "ix_workspace_scheduled_task_schedules_organization_id",
        table_name="workspace_scheduled_task_schedules",
    )
    op.drop_index(
        "ix_workspace_scheduled_task_schedules_next_run_at",
        table_name="workspace_scheduled_task_schedules",
    )
    op.drop_index(
        "ix_workspace_scheduled_task_schedules_is_active",
        table_name="workspace_scheduled_task_schedules",
    )
    op.drop_index(
        "ix_workspace_scheduled_task_schedules_due",
        table_name="workspace_scheduled_task_schedules",
    )
    op.drop_table("workspace_scheduled_task_schedules")

    op.drop_constraint(
        "ck_workspace_scheduled_tasks_schedule_type",
        "workspace_scheduled_tasks",
        type_="check",
    )
    op.execute(
        """
        UPDATE workspace_scheduled_tasks
        SET schedule_type = 'manual', schedule_config = '{}'::jsonb, next_run_at = NULL
        WHERE schedule_type NOT IN ('manual', 'interval', 'daily', 'weekly')
        """
    )
    op.create_check_constraint(
        "ck_workspace_scheduled_tasks_schedule_type",
        "workspace_scheduled_tasks",
        "schedule_type IN ('manual', 'interval', 'daily', 'weekly')",
    )
