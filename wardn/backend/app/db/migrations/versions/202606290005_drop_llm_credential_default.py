"""drop llm credential default flag

Revision ID: 202606290005
Revises: 202606290004
Create Date: 2026-06-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202606290005"
down_revision: str | None = "202606290004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(
        op.f("ix_llm_provider_credentials_is_default"),
        table_name="llm_provider_credentials",
    )
    op.drop_column("llm_provider_credentials", "is_default")


def downgrade() -> None:
    op.add_column(
        "llm_provider_credentials",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("llm_provider_credentials", "is_default", server_default=None)
    op.create_index(
        op.f("ix_llm_provider_credentials_is_default"),
        "llm_provider_credentials",
        ["is_default"],
        unique=False,
    )
