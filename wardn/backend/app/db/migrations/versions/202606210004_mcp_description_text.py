"""use text for mcp server descriptions

Revision ID: 202606210004
Revises: 202606210003
Create Date: 2026-06-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202606210004"
down_revision: str | None = "202606210003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "mcp_server_versions",
        "description",
        existing_type=sa.String(length=100),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "mcp_server_versions",
        "description",
        existing_type=sa.Text(),
        type_=sa.String(length=100),
        existing_nullable=False,
    )
