"""store mcp install secret config

Revision ID: 202606210006
Revises: 202606210005
Create Date: 2026-06-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202606210006"
down_revision: str | None = "202606210005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_server_installations",
        sa.Column(
            "secret_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("mcp_server_installations", "secret_config")
