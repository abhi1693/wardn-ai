"""add llm model prices

Revision ID: 202607090003
Revises: 202607090002
Create Date: 2026-07-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607090003"
down_revision: str | None = "202607090002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_model_prices",
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("input_usd_per_1m_tokens", sa.Numeric(18, 10), nullable=False),
        sa.Column("output_usd_per_1m_tokens", sa.Numeric(18, 10), nullable=False),
        sa.Column("cache_read_usd_per_1m_tokens", sa.Numeric(18, 10), nullable=True),
        sa.Column("cache_write_usd_per_1m_tokens", sa.Numeric(18, 10), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "model", name="uq_llm_model_prices_provider_model"),
    )
    op.create_index(
        op.f("ix_llm_model_prices_model"),
        "llm_model_prices",
        ["model"],
        unique=False,
    )
    op.create_index(
        op.f("ix_llm_model_prices_provider"),
        "llm_model_prices",
        ["provider"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_llm_model_prices_provider"), table_name="llm_model_prices")
    op.drop_index(op.f("ix_llm_model_prices_model"), table_name="llm_model_prices")
    op.drop_table("llm_model_prices")
