"""Link agent runs to their predecessor.

Revision ID: 202608060005
Revises: 202608060004
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202608060005"
down_revision: str | None = "202608060004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("previous_agent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_agent_runs_previous_agent_run_id_agent_runs",
        "agent_runs",
        "agent_runs",
        ["previous_agent_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_agent_runs_previous_agent_run_id"),
        "agent_runs",
        ["previous_agent_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_agent_runs_previous_agent_run_id"), table_name="agent_runs")
    op.drop_constraint(
        "fk_agent_runs_previous_agent_run_id_agent_runs",
        "agent_runs",
        type_="foreignkey",
    )
    op.drop_column("agent_runs", "previous_agent_run_id")
