"""track mcp install artifacts

Revision ID: 202606210005
Revises: 202606210004
Create Date: 2026-06-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202606210005"
down_revision: str | None = "202606210004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_server_installations",
        sa.Column("install_type", sa.String(length=32), nullable=False, server_default="metadata"),
    )
    op.add_column(
        "mcp_server_installations",
        sa.Column("install_path", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "mcp_server_installations",
        sa.Column(
            "runtime_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "mcp_server_installations",
        sa.Column("install_error", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("mcp_server_installations", "install_error")
    op.drop_column("mcp_server_installations", "runtime_config")
    op.drop_column("mcp_server_installations", "install_path")
    op.drop_column("mcp_server_installations", "install_type")
