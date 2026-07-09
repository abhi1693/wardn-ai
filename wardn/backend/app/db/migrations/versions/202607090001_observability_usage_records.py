"""add observability usage records

Revision ID: 202607090001
Revises: 202607070002
Create Date: 2026-07-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607090001"
down_revision: str | None = "202607070002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_traces",
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("span_id", sa.String(length=32), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Numeric(18, 10), nullable=False),
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
    )
    op.create_index(op.f("ix_llm_traces_span_id"), "llm_traces", ["span_id"], unique=False)
    op.create_index(op.f("ix_llm_traces_trace_id"), "llm_traces", ["trace_id"], unique=False)
    op.create_index(
        "ix_llm_traces_trace_span",
        "llm_traces",
        ["trace_id", "span_id"],
        unique=False,
    )

    op.create_table(
        "llm_usage_records",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(18, 10), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("span_id", sa.String(length=32), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
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
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_llm_usage_records_agent_id"),
        "llm_usage_records",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_llm_usage_records_agent_run_id"),
        "llm_usage_records",
        ["agent_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_llm_usage_records_model"),
        "llm_usage_records",
        ["model"],
        unique=False,
    )
    op.create_index(
        op.f("ix_llm_usage_records_organization_id"),
        "llm_usage_records",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_llm_usage_records_org_agent_started",
        "llm_usage_records",
        ["organization_id", "agent_id", "started_at"],
        unique=False,
    )
    op.create_index(
        "ix_llm_usage_records_org_model_started",
        "llm_usage_records",
        ["organization_id", "provider", "model", "started_at"],
        unique=False,
    )
    op.create_index(
        "ix_llm_usage_records_org_user_started",
        "llm_usage_records",
        ["organization_id", "user_id", "started_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_llm_usage_records_provider"),
        "llm_usage_records",
        ["provider"],
        unique=False,
    )
    op.create_index(
        op.f("ix_llm_usage_records_span_id"),
        "llm_usage_records",
        ["span_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_llm_usage_records_status"),
        "llm_usage_records",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_llm_usage_records_trace_id"),
        "llm_usage_records",
        ["trace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_llm_usage_records_user_id"),
        "llm_usage_records",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_llm_usage_records_workspace_id"),
        "llm_usage_records",
        ["workspace_id"],
        unique=False,
    )

    op.add_column(
        "mcp_tool_invocations",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "mcp_tool_invocations",
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "mcp_tool_invocations",
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_mcp_tool_invocations_user_id_users",
        "mcp_tool_invocations",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_mcp_tool_invocations_agent_id_agents",
        "mcp_tool_invocations",
        "agents",
        ["agent_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_mcp_tool_invocations_agent_run_id_agent_runs",
        "mcp_tool_invocations",
        "agent_runs",
        ["agent_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_mcp_tool_invocations_user_id"),
        "mcp_tool_invocations",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_tool_invocations_agent_id"),
        "mcp_tool_invocations",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_tool_invocations_agent_run_id"),
        "mcp_tool_invocations",
        ["agent_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_mcp_tool_invocations_workspace_user_started",
        "mcp_tool_invocations",
        ["workspace_id", "user_id", "started_at"],
        unique=False,
    )
    op.create_index(
        "ix_mcp_tool_invocations_workspace_agent_started",
        "mcp_tool_invocations",
        ["workspace_id", "agent_id", "started_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mcp_tool_invocations_workspace_agent_started",
        table_name="mcp_tool_invocations",
    )
    op.drop_index(
        "ix_mcp_tool_invocations_workspace_user_started",
        table_name="mcp_tool_invocations",
    )
    op.drop_index(
        op.f("ix_mcp_tool_invocations_agent_run_id"),
        table_name="mcp_tool_invocations",
    )
    op.drop_index(op.f("ix_mcp_tool_invocations_agent_id"), table_name="mcp_tool_invocations")
    op.drop_index(op.f("ix_mcp_tool_invocations_user_id"), table_name="mcp_tool_invocations")
    op.drop_constraint(
        "fk_mcp_tool_invocations_agent_run_id_agent_runs",
        "mcp_tool_invocations",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_mcp_tool_invocations_agent_id_agents",
        "mcp_tool_invocations",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_mcp_tool_invocations_user_id_users",
        "mcp_tool_invocations",
        type_="foreignkey",
    )
    op.drop_column("mcp_tool_invocations", "agent_run_id")
    op.drop_column("mcp_tool_invocations", "agent_id")
    op.drop_column("mcp_tool_invocations", "user_id")

    op.drop_index(op.f("ix_llm_usage_records_workspace_id"), table_name="llm_usage_records")
    op.drop_index(op.f("ix_llm_usage_records_user_id"), table_name="llm_usage_records")
    op.drop_index(op.f("ix_llm_usage_records_trace_id"), table_name="llm_usage_records")
    op.drop_index(op.f("ix_llm_usage_records_status"), table_name="llm_usage_records")
    op.drop_index(op.f("ix_llm_usage_records_span_id"), table_name="llm_usage_records")
    op.drop_index(op.f("ix_llm_usage_records_provider"), table_name="llm_usage_records")
    op.drop_index("ix_llm_usage_records_org_user_started", table_name="llm_usage_records")
    op.drop_index("ix_llm_usage_records_org_model_started", table_name="llm_usage_records")
    op.drop_index("ix_llm_usage_records_org_agent_started", table_name="llm_usage_records")
    op.drop_index(op.f("ix_llm_usage_records_organization_id"), table_name="llm_usage_records")
    op.drop_index(op.f("ix_llm_usage_records_model"), table_name="llm_usage_records")
    op.drop_index(op.f("ix_llm_usage_records_agent_run_id"), table_name="llm_usage_records")
    op.drop_index(op.f("ix_llm_usage_records_agent_id"), table_name="llm_usage_records")
    op.drop_table("llm_usage_records")

    op.drop_index("ix_llm_traces_trace_span", table_name="llm_traces")
    op.drop_index(op.f("ix_llm_traces_trace_id"), table_name="llm_traces")
    op.drop_index(op.f("ix_llm_traces_span_id"), table_name="llm_traces")
    op.drop_table("llm_traces")
