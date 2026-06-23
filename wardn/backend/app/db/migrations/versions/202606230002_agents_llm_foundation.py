"""add agents and llm provider credentials

Revision ID: 202606230002
Revises: 202606230001
Create Date: 2026-06-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202606230002"
down_revision: str | None = "202606230001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_provider_credentials",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("visibility", sa.String(length=32), nullable=False),
        sa.Column("secret_value", sa.Text(), nullable=False),
        sa.Column("base_url", sa.String(length=2048), nullable=False),
        sa.Column(
            "extra_headers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
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
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "name", name="uq_llm_provider_credentials_org_name"),
    )
    op.create_index(
        op.f("ix_llm_provider_credentials_is_active"),
        "llm_provider_credentials",
        ["is_active"],
        unique=False,
    )
    op.create_index(
        op.f("ix_llm_provider_credentials_is_default"),
        "llm_provider_credentials",
        ["is_default"],
        unique=False,
    )
    op.create_index(
        op.f("ix_llm_provider_credentials_organization_id"),
        "llm_provider_credentials",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_llm_provider_credentials_provider"),
        "llm_provider_credentials",
        ["provider"],
        unique=False,
    )
    op.create_index(
        op.f("ix_llm_provider_credentials_user_id"),
        "llm_provider_credentials",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_llm_provider_credentials_visibility"),
        "llm_provider_credentials",
        ["visibility"],
        unique=False,
    )
    op.create_index(
        op.f("ix_llm_provider_credentials_workspace_id"),
        "llm_provider_credentials",
        ["workspace_id"],
        unique=False,
    )

    op.create_table(
        "agents",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider_credential_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["provider_credential_id"],
            ["llm_provider_credentials.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "name", name="uq_agents_org_name"),
    )
    op.create_index(op.f("ix_agents_created_by_id"), "agents", ["created_by_id"], unique=False)
    op.create_index(op.f("ix_agents_is_active"), "agents", ["is_active"], unique=False)
    op.create_index(op.f("ix_agents_organization_id"), "agents", ["organization_id"], unique=False)
    op.create_index(
        op.f("ix_agents_provider_credential_id"),
        "agents",
        ["provider_credential_id"],
        unique=False,
    )
    op.create_index(op.f("ix_agents_workspace_id"), "agents", ["workspace_id"], unique=False)

    op.create_table(
        "agent_tools",
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_schema_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("installation_id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["installation_id"],
            ["mcp_server_installations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tool_schema_id"],
            ["mcp_server_tool_schemas.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", "tool_schema_id", name="uq_agent_tools_agent_tool_schema"),
    )
    op.create_index(op.f("ix_agent_tools_agent_id"), "agent_tools", ["agent_id"], unique=False)
    op.create_index(
        op.f("ix_agent_tools_installation_id"),
        "agent_tools",
        ["installation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_tools_tool_schema_id"),
        "agent_tools",
        ["tool_schema_id"],
        unique=False,
    )

    op.alter_column("llm_provider_credentials", "extra_headers", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_agent_tools_tool_schema_id"), table_name="agent_tools")
    op.drop_index(op.f("ix_agent_tools_installation_id"), table_name="agent_tools")
    op.drop_index(op.f("ix_agent_tools_agent_id"), table_name="agent_tools")
    op.drop_table("agent_tools")

    op.drop_index(op.f("ix_agents_workspace_id"), table_name="agents")
    op.drop_index(op.f("ix_agents_provider_credential_id"), table_name="agents")
    op.drop_index(op.f("ix_agents_organization_id"), table_name="agents")
    op.drop_index(op.f("ix_agents_is_active"), table_name="agents")
    op.drop_index(op.f("ix_agents_created_by_id"), table_name="agents")
    op.drop_table("agents")

    op.drop_index(
        op.f("ix_llm_provider_credentials_workspace_id"),
        table_name="llm_provider_credentials",
    )
    op.drop_index(
        op.f("ix_llm_provider_credentials_visibility"),
        table_name="llm_provider_credentials",
    )
    op.drop_index(
        op.f("ix_llm_provider_credentials_user_id"),
        table_name="llm_provider_credentials",
    )
    op.drop_index(
        op.f("ix_llm_provider_credentials_provider"),
        table_name="llm_provider_credentials",
    )
    op.drop_index(
        op.f("ix_llm_provider_credentials_organization_id"),
        table_name="llm_provider_credentials",
    )
    op.drop_index(
        op.f("ix_llm_provider_credentials_is_default"),
        table_name="llm_provider_credentials",
    )
    op.drop_index(
        op.f("ix_llm_provider_credentials_is_active"),
        table_name="llm_provider_credentials",
    )
    op.drop_table("llm_provider_credentials")
