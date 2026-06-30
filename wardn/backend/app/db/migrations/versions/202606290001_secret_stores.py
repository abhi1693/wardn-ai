"""add external secret stores

Revision ID: 202606290001
Revises: 202606230007
Create Date: 2026-06-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202606290001"
down_revision: str | None = "202606230007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "secret_stores",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "auth_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "name",
            name="uq_secret_stores_org_workspace_name",
        ),
    )
    op.create_index(
        op.f("ix_secret_stores_created_by_id"),
        "secret_stores",
        ["created_by_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_secret_stores_is_active"),
        "secret_stores",
        ["is_active"],
        unique=False,
    )
    op.create_index(
        op.f("ix_secret_stores_is_default"),
        "secret_stores",
        ["is_default"],
        unique=False,
    )
    op.create_index(
        op.f("ix_secret_stores_organization_id"),
        "secret_stores",
        ["organization_id"],
        unique=False,
    )
    op.create_index(op.f("ix_secret_stores_provider"), "secret_stores", ["provider"], unique=False)
    op.create_index(
        op.f("ix_secret_stores_workspace_id"),
        "secret_stores",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "uq_secret_stores_org_name",
        "secret_stores",
        ["organization_id", "name"],
        unique=True,
        postgresql_where=sa.text("workspace_id is null"),
    )
    op.create_index(
        "uq_secret_stores_org_default",
        "secret_stores",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text("workspace_id is null and is_default is true"),
    )
    op.create_index(
        "uq_secret_stores_workspace_default",
        "secret_stores",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("workspace_id is not null and is_default is true"),
    )

    op.create_table(
        "secret_handles",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("purpose", sa.String(length=50), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("external_ref", sa.Text(), nullable=False),
        sa.Column("key_name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=100), nullable=False),
        sa.Column(
            "handle_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["store_id"], ["secret_stores.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "display_name",
            name="uq_secret_handles_org_workspace_display_name",
        ),
    )
    op.create_index(
        op.f("ix_secret_handles_created_by_id"),
        "secret_handles",
        ["created_by_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_secret_handles_organization_id"),
        "secret_handles",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_secret_handles_purpose"),
        "secret_handles",
        ["purpose"],
        unique=False,
    )
    op.create_index(
        op.f("ix_secret_handles_store_id"),
        "secret_handles",
        ["store_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_secret_handles_workspace_id"),
        "secret_handles",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "uq_secret_handles_org_display_name",
        "secret_handles",
        ["organization_id", "display_name"],
        unique=True,
        postgresql_where=sa.text("workspace_id is null"),
    )


def downgrade() -> None:
    op.drop_index("uq_secret_handles_org_display_name", table_name="secret_handles")
    op.drop_index(op.f("ix_secret_handles_workspace_id"), table_name="secret_handles")
    op.drop_index(op.f("ix_secret_handles_store_id"), table_name="secret_handles")
    op.drop_index(op.f("ix_secret_handles_purpose"), table_name="secret_handles")
    op.drop_index(op.f("ix_secret_handles_organization_id"), table_name="secret_handles")
    op.drop_index(op.f("ix_secret_handles_created_by_id"), table_name="secret_handles")
    op.drop_table("secret_handles")

    op.drop_index("uq_secret_stores_workspace_default", table_name="secret_stores")
    op.drop_index("uq_secret_stores_org_default", table_name="secret_stores")
    op.drop_index("uq_secret_stores_org_name", table_name="secret_stores")
    op.drop_index(op.f("ix_secret_stores_workspace_id"), table_name="secret_stores")
    op.drop_index(op.f("ix_secret_stores_provider"), table_name="secret_stores")
    op.drop_index(op.f("ix_secret_stores_organization_id"), table_name="secret_stores")
    op.drop_index(op.f("ix_secret_stores_is_default"), table_name="secret_stores")
    op.drop_index(op.f("ix_secret_stores_is_active"), table_name="secret_stores")
    op.drop_index(op.f("ix_secret_stores_created_by_id"), table_name="secret_stores")
    op.drop_table("secret_stores")
