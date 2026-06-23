"""add llm provider oauth states

Revision ID: 202606230004
Revises: 202606230003
Create Date: 2026-06-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202606230004"
down_revision: str | None = "202606230003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_provider_oauth_states",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.String(length=128), nullable=False),
        sa.Column("code_verifier", sa.String(length=256), nullable=False),
        sa.Column("redirect_uri", sa.String(length=2048), nullable=False),
        sa.Column("oauth_provider", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("visibility", sa.String(length=32), nullable=False),
        sa.Column("base_url", sa.String(length=2048), nullable=False),
        sa.Column(
            "extra_headers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("success_redirect_path", sa.String(length=2048), nullable=False),
        sa.Column("failure_redirect_path", sa.String(length=2048), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state"),
    )
    op.create_index(
        op.f("ix_llm_provider_oauth_states_expires_at"),
        "llm_provider_oauth_states",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_llm_provider_oauth_states_oauth_provider"),
        "llm_provider_oauth_states",
        ["oauth_provider"],
        unique=False,
    )
    op.create_index(
        op.f("ix_llm_provider_oauth_states_organization_id"),
        "llm_provider_oauth_states",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_llm_provider_oauth_states_state"),
        "llm_provider_oauth_states",
        ["state"],
        unique=True,
    )
    op.create_index(
        op.f("ix_llm_provider_oauth_states_user_id"),
        "llm_provider_oauth_states",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_llm_provider_oauth_states_workspace_id"),
        "llm_provider_oauth_states",
        ["workspace_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_llm_provider_oauth_states_workspace_id"),
        table_name="llm_provider_oauth_states",
    )
    op.drop_index(
        op.f("ix_llm_provider_oauth_states_user_id"),
        table_name="llm_provider_oauth_states",
    )
    op.drop_index(
        op.f("ix_llm_provider_oauth_states_state"),
        table_name="llm_provider_oauth_states",
    )
    op.drop_index(
        op.f("ix_llm_provider_oauth_states_organization_id"),
        table_name="llm_provider_oauth_states",
    )
    op.drop_index(
        op.f("ix_llm_provider_oauth_states_oauth_provider"),
        table_name="llm_provider_oauth_states",
    )
    op.drop_index(
        op.f("ix_llm_provider_oauth_states_expires_at"),
        table_name="llm_provider_oauth_states",
    )
    op.drop_table("llm_provider_oauth_states")
