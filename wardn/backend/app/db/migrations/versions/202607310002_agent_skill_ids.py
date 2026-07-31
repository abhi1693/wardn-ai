"""Add installed skill IDs to agents.

Revision ID: 202607310002
Revises: 202607310001
Create Date: 2026-07-31 00:02:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision: str = "202607310002"
down_revision: str | None = "202607310001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "skill_ids",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
    )
    op.alter_column("agents", "skill_ids", server_default=None)


def downgrade() -> None:
    op.drop_column("agents", "skill_ids")
