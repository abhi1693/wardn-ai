"""add api token gateway scopes

Revision ID: 202606230001
Revises: 202606210015
Create Date: 2026-06-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202606230001"
down_revision: str | None = "202606210015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_api_tokens",
        sa.Column(
            "organization_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "user_api_tokens",
        sa.Column(
            "workspace_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.alter_column("user_api_tokens", "organization_ids", server_default=None)
    op.alter_column("user_api_tokens", "workspace_ids", server_default=None)


def downgrade() -> None:
    op.drop_column("user_api_tokens", "workspace_ids")
    op.drop_column("user_api_tokens", "organization_ids")
