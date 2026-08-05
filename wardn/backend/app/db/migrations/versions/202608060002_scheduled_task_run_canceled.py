"""Add canceled scheduled task run status.

Revision ID: 202608060002
Revises: 202608060001
Create Date: 2026-08-06 01:25:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608060002"
down_revision: str | None = "202608060001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


OLD_STATUS_CHECK = (
    "status IN ("
    "'queued', 'running', 'succeeded', 'partially_delivered', "
    "'delivery_failed', 'failed', 'waiting_confirmation'"
    ")"
)

NEW_STATUS_CHECK = (
    "status IN ("
    "'queued', 'running', 'succeeded', 'partially_delivered', "
    "'delivery_failed', 'failed', 'waiting_confirmation', 'canceled'"
    ")"
)


def upgrade() -> None:
    op.drop_constraint(
        "ck_workspace_scheduled_task_runs_status",
        "workspace_scheduled_task_runs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_workspace_scheduled_task_runs_status",
        "workspace_scheduled_task_runs",
        sa.text(NEW_STATUS_CHECK),
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_workspace_scheduled_task_runs_status",
        "workspace_scheduled_task_runs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_workspace_scheduled_task_runs_status",
        "workspace_scheduled_task_runs",
        sa.text(OLD_STATUS_CHECK),
    )
