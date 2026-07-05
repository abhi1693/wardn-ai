"""add guardrail policies

Revision ID: 202607050003
Revises: 202607050002
Create Date: 2026-07-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607050003"
down_revision: str | None = "202607050002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "guardrail_policies",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("installation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tool_schema_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("conditions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
        sa.CheckConstraint(
            "mode in ('allow', 'deny', 'require_confirmation')",
            name="ck_guardrail_policies_mode",
        ),
        sa.CheckConstraint("priority >= 0", name="ck_guardrail_policies_priority"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["installation_id"],
            ["mcp_server_installations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tool_schema_id"],
            ["mcp_server_tool_schemas.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_guardrail_policies_scope",
        "guardrail_policies",
        ["organization_id", "workspace_id", "is_active"],
        unique=False,
    )
    op.create_index(
        "ix_guardrail_policies_targets",
        "guardrail_policies",
        ["agent_id", "installation_id", "tool_schema_id"],
        unique=False,
    )
    op.create_index(
        "uq_guardrail_policies_org_name",
        "guardrail_policies",
        ["organization_id", "name"],
        unique=True,
        postgresql_where=sa.text("workspace_id is null"),
    )
    op.create_index(
        "uq_guardrail_policies_workspace_name",
        "guardrail_policies",
        ["organization_id", "workspace_id", "name"],
        unique=True,
        postgresql_where=sa.text("workspace_id is not null"),
    )
    op.create_index(op.f("ix_guardrail_policies_agent_id"), "guardrail_policies", ["agent_id"])
    op.create_index(
        op.f("ix_guardrail_policies_created_by_id"),
        "guardrail_policies",
        ["created_by_id"],
    )
    op.create_index(
        op.f("ix_guardrail_policies_installation_id"),
        "guardrail_policies",
        ["installation_id"],
    )
    op.create_index(
        op.f("ix_guardrail_policies_is_active"),
        "guardrail_policies",
        ["is_active"],
    )
    op.create_index(op.f("ix_guardrail_policies_mode"), "guardrail_policies", ["mode"])
    op.create_index(
        op.f("ix_guardrail_policies_organization_id"),
        "guardrail_policies",
        ["organization_id"],
    )
    op.create_index(
        op.f("ix_guardrail_policies_priority"),
        "guardrail_policies",
        ["priority"],
    )
    op.create_index(
        op.f("ix_guardrail_policies_tool_schema_id"),
        "guardrail_policies",
        ["tool_schema_id"],
    )
    op.create_index(
        op.f("ix_guardrail_policies_workspace_id"),
        "guardrail_policies",
        ["workspace_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_guardrail_policies_workspace_id"), table_name="guardrail_policies")
    op.drop_index(op.f("ix_guardrail_policies_tool_schema_id"), table_name="guardrail_policies")
    op.drop_index(op.f("ix_guardrail_policies_priority"), table_name="guardrail_policies")
    op.drop_index(op.f("ix_guardrail_policies_organization_id"), table_name="guardrail_policies")
    op.drop_index(op.f("ix_guardrail_policies_mode"), table_name="guardrail_policies")
    op.drop_index(op.f("ix_guardrail_policies_is_active"), table_name="guardrail_policies")
    op.drop_index(op.f("ix_guardrail_policies_installation_id"), table_name="guardrail_policies")
    op.drop_index(op.f("ix_guardrail_policies_created_by_id"), table_name="guardrail_policies")
    op.drop_index(op.f("ix_guardrail_policies_agent_id"), table_name="guardrail_policies")
    op.drop_index("uq_guardrail_policies_workspace_name", table_name="guardrail_policies")
    op.drop_index("uq_guardrail_policies_org_name", table_name="guardrail_policies")
    op.drop_index("ix_guardrail_policies_targets", table_name="guardrail_policies")
    op.drop_index("ix_guardrail_policies_scope", table_name="guardrail_policies")
    op.drop_table("guardrail_policies")
