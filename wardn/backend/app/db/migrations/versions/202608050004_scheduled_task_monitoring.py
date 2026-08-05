"""add scheduled task monitoring mode

Revision ID: 202608050004
Revises: 202608050003
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202608050004"
down_revision: str | None = "202608050003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DEFAULT_MONITORING_CONFIG = (
    """'{"enabled": false, "notify_on_change": true, """
    """"deliver_on_change_only": true, "baseline_on_first_run": true, """
    """"stop_conditions": {}}'::jsonb"""
)


def upgrade() -> None:
    op.add_column(
        "workspace_scheduled_tasks",
        sa.Column(
            "monitoring_config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text(DEFAULT_MONITORING_CONFIG),
            nullable=False,
        ),
    )
    op.add_column(
        "workspace_scheduled_tasks",
        sa.Column(
            "monitoring_status",
            sa.String(length=32),
            server_default="off",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_workspace_scheduled_tasks_monitoring_status",
        "workspace_scheduled_tasks",
        (
            "monitoring_status IN ("
            "'off', 'watching', 'baseline', 'changed', 'unchanged', "
            "'no_output', 'stopped'"
            ")"
        ),
    )
    op.create_index(
        "ix_workspace_scheduled_tasks_monitoring_status",
        "workspace_scheduled_tasks",
        ["monitoring_status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workspace_scheduled_tasks_monitoring_status",
        table_name="workspace_scheduled_tasks",
    )
    op.drop_constraint(
        "ck_workspace_scheduled_tasks_monitoring_status",
        "workspace_scheduled_tasks",
        type_="check",
    )
    op.drop_column("workspace_scheduled_tasks", "monitoring_status")
    op.drop_column("workspace_scheduled_tasks", "monitoring_config")
