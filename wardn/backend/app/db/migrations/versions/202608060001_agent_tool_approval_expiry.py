"""Add agent tool approval expiry.

Revision ID: 202608060001
Revises: 202608050006
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608060001"
down_revision: str | None = "202608050006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_tool_approvals",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_agent_tool_approvals_expires_at"),
        "agent_tool_approvals",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_agent_tool_approvals_expires_at"),
        table_name="agent_tool_approvals",
    )
    op.drop_column("agent_tool_approvals", "expires_at")
