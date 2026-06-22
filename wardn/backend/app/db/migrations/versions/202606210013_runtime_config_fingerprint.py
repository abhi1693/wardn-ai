"""Add runtime config fingerprints.

Revision ID: 202606210013
Revises: 202606210012
Create Date: 2026-06-21 00:13:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202606210013"
down_revision: str | None = "202606210012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_runtime_sessions",
        sa.Column(
            "config_fingerprint",
            sa.String(length=64),
            nullable=False,
            server_default="",
        ),
    )
    op.create_index(
        "ix_mcp_runtime_sessions_installation_config_fingerprint",
        "mcp_runtime_sessions",
        ["installation_id", "config_fingerprint"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mcp_runtime_sessions_installation_config_fingerprint",
        table_name="mcp_runtime_sessions",
    )
    op.drop_column("mcp_runtime_sessions", "config_fingerprint")
