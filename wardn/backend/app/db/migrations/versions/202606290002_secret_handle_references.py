"""migrate secret-bearing models to external handle references

Revision ID: 202606290002
Revises: 202606290001
Create Date: 2026-06-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202606290002"
down_revision: str | None = "202606290001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "llm_provider_credentials",
        sa.Column("api_key_secret_handle_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "llm_provider_credentials",
        sa.Column(
            "oauth_access_token_secret_handle_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "llm_provider_credentials",
        sa.Column(
            "oauth_refresh_token_secret_handle_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_index(
        op.f("ix_llm_provider_credentials_api_key_secret_handle_id"),
        "llm_provider_credentials",
        ["api_key_secret_handle_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_llm_provider_credentials_oauth_access_token_secret_handle_id"),
        "llm_provider_credentials",
        ["oauth_access_token_secret_handle_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_llm_provider_credentials_oauth_refresh_token_secret_handle_id"),
        "llm_provider_credentials",
        ["oauth_refresh_token_secret_handle_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_llm_provider_credentials_api_key_secret_handle",
        "llm_provider_credentials",
        "secret_handles",
        ["api_key_secret_handle_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_llm_provider_credentials_oauth_access_secret_handle",
        "llm_provider_credentials",
        "secret_handles",
        ["oauth_access_token_secret_handle_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_llm_provider_credentials_oauth_refresh_secret_handle",
        "llm_provider_credentials",
        "secret_handles",
        ["oauth_refresh_token_secret_handle_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_column("llm_provider_credentials", "secret_value")
    op.drop_column("llm_provider_credentials", "oauth_access_token")
    op.drop_column("llm_provider_credentials", "oauth_refresh_token")

    op.add_column(
        "mcp_catalog_sources",
        sa.Column("auth_secret_handle_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        op.f("ix_mcp_catalog_sources_auth_secret_handle_id"),
        "mcp_catalog_sources",
        ["auth_secret_handle_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_mcp_catalog_sources_auth_secret_handle",
        "mcp_catalog_sources",
        "secret_handles",
        ["auth_secret_handle_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_column("mcp_catalog_sources", "secret_config")

    op.execute(
        sa.text(
            """
            update mcp_server_installations
            set secret_config = '{}'::jsonb
            where secret_config is not null
              and secret_config <> '{}'::jsonb
            """
        )
    )
    op.alter_column(
        "mcp_server_installations",
        "secret_config",
        new_column_name="secret_references",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "mcp_server_installations",
        "secret_references",
        new_column_name="secret_config",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        existing_nullable=False,
    )

    op.add_column(
        "mcp_catalog_sources",
        sa.Column(
            "secret_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column("mcp_catalog_sources", "secret_config", server_default=None)
    op.drop_constraint(
        "fk_mcp_catalog_sources_auth_secret_handle",
        "mcp_catalog_sources",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_mcp_catalog_sources_auth_secret_handle_id"),
        table_name="mcp_catalog_sources",
    )
    op.drop_column("mcp_catalog_sources", "auth_secret_handle_id")

    op.add_column(
        "llm_provider_credentials",
        sa.Column("oauth_refresh_token", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "llm_provider_credentials",
        sa.Column("oauth_access_token", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "llm_provider_credentials",
        sa.Column("secret_value", sa.Text(), nullable=False, server_default=""),
    )
    op.alter_column("llm_provider_credentials", "oauth_refresh_token", server_default=None)
    op.alter_column("llm_provider_credentials", "oauth_access_token", server_default=None)
    op.alter_column("llm_provider_credentials", "secret_value", server_default=None)
    op.drop_constraint(
        "fk_llm_provider_credentials_oauth_refresh_secret_handle",
        "llm_provider_credentials",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_llm_provider_credentials_oauth_access_secret_handle",
        "llm_provider_credentials",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_llm_provider_credentials_api_key_secret_handle",
        "llm_provider_credentials",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_llm_provider_credentials_oauth_refresh_token_secret_handle_id"),
        table_name="llm_provider_credentials",
    )
    op.drop_index(
        op.f("ix_llm_provider_credentials_oauth_access_token_secret_handle_id"),
        table_name="llm_provider_credentials",
    )
    op.drop_index(
        op.f("ix_llm_provider_credentials_api_key_secret_handle_id"),
        table_name="llm_provider_credentials",
    )
    op.drop_column("llm_provider_credentials", "oauth_refresh_token_secret_handle_id")
    op.drop_column("llm_provider_credentials", "oauth_access_token_secret_handle_id")
    op.drop_column("llm_provider_credentials", "api_key_secret_handle_id")
