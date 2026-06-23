"""add oauth support to llm provider credentials

Revision ID: 202606230003
Revises: 202606230002
Create Date: 2026-06-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202606230003"
down_revision: str | None = "202606230002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "llm_provider_credentials",
        sa.Column(
            "auth_method",
            sa.String(length=32),
            nullable=False,
            server_default="api_key",
        ),
    )
    op.add_column(
        "llm_provider_credentials",
        sa.Column(
            "oauth_provider",
            sa.String(length=50),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "llm_provider_credentials",
        sa.Column("oauth_access_token", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "llm_provider_credentials",
        sa.Column("oauth_refresh_token", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "llm_provider_credentials",
        sa.Column("oauth_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "llm_provider_credentials",
        sa.Column(
            "oauth_scopes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "llm_provider_credentials",
        sa.Column(
            "oauth_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(
        op.f("ix_llm_provider_credentials_auth_method"),
        "llm_provider_credentials",
        ["auth_method"],
        unique=False,
    )
    op.create_index(
        op.f("ix_llm_provider_credentials_oauth_provider"),
        "llm_provider_credentials",
        ["oauth_provider"],
        unique=False,
    )
    op.alter_column("llm_provider_credentials", "auth_method", server_default=None)
    op.alter_column("llm_provider_credentials", "oauth_provider", server_default=None)
    op.alter_column("llm_provider_credentials", "oauth_access_token", server_default=None)
    op.alter_column("llm_provider_credentials", "oauth_refresh_token", server_default=None)
    op.alter_column("llm_provider_credentials", "oauth_scopes", server_default=None)
    op.alter_column("llm_provider_credentials", "oauth_metadata", server_default=None)


def downgrade() -> None:
    op.drop_index(
        op.f("ix_llm_provider_credentials_oauth_provider"),
        table_name="llm_provider_credentials",
    )
    op.drop_index(
        op.f("ix_llm_provider_credentials_auth_method"),
        table_name="llm_provider_credentials",
    )
    op.drop_column("llm_provider_credentials", "oauth_metadata")
    op.drop_column("llm_provider_credentials", "oauth_scopes")
    op.drop_column("llm_provider_credentials", "oauth_expires_at")
    op.drop_column("llm_provider_credentials", "oauth_refresh_token")
    op.drop_column("llm_provider_credentials", "oauth_access_token")
    op.drop_column("llm_provider_credentials", "oauth_provider")
    op.drop_column("llm_provider_credentials", "auth_method")
