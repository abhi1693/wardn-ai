"""add delivery-aware scheduled task run statuses

Revision ID: 202608050002
Revises: 202608050001
Create Date: 2026-08-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202608050002"
down_revision: str | None = "202608050001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_workspace_scheduled_task_runs_status",
        "workspace_scheduled_task_runs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_workspace_scheduled_task_runs_status",
        "workspace_scheduled_task_runs",
        (
            "status IN ("
            "'queued', 'running', 'succeeded', 'partially_delivered', "
            "'delivery_failed', 'failed', 'waiting_confirmation'"
            ")"
        ),
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE workspace_scheduled_task_runs
        SET status = CASE
            WHEN status = 'partially_delivered' THEN 'succeeded'
            WHEN status = 'delivery_failed' THEN 'failed'
            ELSE status
        END
        WHERE status IN ('partially_delivered', 'delivery_failed')
        """
    )
    op.drop_constraint(
        "ck_workspace_scheduled_task_runs_status",
        "workspace_scheduled_task_runs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_workspace_scheduled_task_runs_status",
        "workspace_scheduled_task_runs",
        "status IN ('queued', 'running', 'succeeded', 'failed', 'waiting_confirmation')",
    )
