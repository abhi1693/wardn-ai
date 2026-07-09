"""backfill mcp tool usage organization attribution

Revision ID: 202607090002
Revises: 202607090001
Create Date: 2026-07-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202607090002"
down_revision: str | None = "202607090001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        update mcp_runtime_sessions as runtime_session
        set organization_id = workspace.organization_id
        from workspaces as workspace
        where runtime_session.workspace_id = workspace.id
          and runtime_session.organization_id is null
        """
    )
    op.execute(
        """
        update mcp_tool_invocations as invocation
        set organization_id = workspace.organization_id
        from workspaces as workspace
        where invocation.workspace_id = workspace.id
          and invocation.organization_id is null
        """
    )


def downgrade() -> None:
    pass
