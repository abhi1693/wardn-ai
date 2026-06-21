"""track mcp runtime sessions and tool invocations

Revision ID: 202606210008
Revises: 202606210007
Create Date: 2026-06-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202606210008"
down_revision: str | None = "202606210007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_runtime_sessions",
        sa.Column("installation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("server_name", sa.String(length=200), nullable=False),
        sa.Column("server_version", sa.String(length=255), nullable=False),
        sa.Column("runtime_provider", sa.String(length=32), nullable=False),
        sa.Column("runtime_kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("pod_name", sa.String(length=253), nullable=False),
        sa.Column("namespace", sa.String(length=253), nullable=False),
        sa.Column("endpoint_url", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["installation_id"],
            ["mcp_server_installations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_mcp_runtime_sessions_installation_id"),
        "mcp_runtime_sessions",
        ["installation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_runtime_sessions_runtime_kind"),
        "mcp_runtime_sessions",
        ["runtime_kind"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_runtime_sessions_runtime_provider"),
        "mcp_runtime_sessions",
        ["runtime_provider"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_runtime_sessions_server_name"),
        "mcp_runtime_sessions",
        ["server_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_runtime_sessions_server_version"),
        "mcp_runtime_sessions",
        ["server_version"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_runtime_sessions_status"),
        "mcp_runtime_sessions",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_mcp_runtime_sessions_status_expires_at",
        "mcp_runtime_sessions",
        ["status", "expires_at"],
        unique=False,
    )
    op.create_index(
        "uq_mcp_runtime_sessions_one_active_per_installation",
        "mcp_runtime_sessions",
        ["installation_id"],
        unique=True,
        postgresql_where=sa.text(
            "status in ('pending', 'starting', 'running', 'idle')"
        ),
    )

    op.create_table(
        "mcp_tool_invocations",
        sa.Column("runtime_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("installation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("server_name", sa.String(length=200), nullable=False),
        sa.Column("server_version", sa.String(length=255), nullable=False),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("input_size_bytes", sa.Integer(), nullable=False),
        sa.Column("output_size_bytes", sa.Integer(), nullable=False),
        sa.Column("is_error", sa.Boolean(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["installation_id"],
            ["mcp_server_installations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["runtime_session_id"],
            ["mcp_runtime_sessions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_mcp_tool_invocations_installation_id"),
        "mcp_tool_invocations",
        ["installation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_tool_invocations_runtime_session_id"),
        "mcp_tool_invocations",
        ["runtime_session_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_tool_invocations_server_name"),
        "mcp_tool_invocations",
        ["server_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_tool_invocations_server_version"),
        "mcp_tool_invocations",
        ["server_version"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_tool_invocations_status"),
        "mcp_tool_invocations",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_tool_invocations_tool_name"),
        "mcp_tool_invocations",
        ["tool_name"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_mcp_tool_invocations_tool_name"), table_name="mcp_tool_invocations")
    op.drop_index(op.f("ix_mcp_tool_invocations_status"), table_name="mcp_tool_invocations")
    op.drop_index(
        op.f("ix_mcp_tool_invocations_server_version"),
        table_name="mcp_tool_invocations",
    )
    op.drop_index(
        op.f("ix_mcp_tool_invocations_server_name"),
        table_name="mcp_tool_invocations",
    )
    op.drop_index(
        op.f("ix_mcp_tool_invocations_runtime_session_id"),
        table_name="mcp_tool_invocations",
    )
    op.drop_index(
        op.f("ix_mcp_tool_invocations_installation_id"),
        table_name="mcp_tool_invocations",
    )
    op.drop_table("mcp_tool_invocations")

    op.drop_index(
        "uq_mcp_runtime_sessions_one_active_per_installation",
        table_name="mcp_runtime_sessions",
    )
    op.drop_index(
        "ix_mcp_runtime_sessions_status_expires_at",
        table_name="mcp_runtime_sessions",
    )
    op.drop_index(op.f("ix_mcp_runtime_sessions_status"), table_name="mcp_runtime_sessions")
    op.drop_index(
        op.f("ix_mcp_runtime_sessions_server_version"),
        table_name="mcp_runtime_sessions",
    )
    op.drop_index(
        op.f("ix_mcp_runtime_sessions_server_name"),
        table_name="mcp_runtime_sessions",
    )
    op.drop_index(
        op.f("ix_mcp_runtime_sessions_runtime_provider"),
        table_name="mcp_runtime_sessions",
    )
    op.drop_index(
        op.f("ix_mcp_runtime_sessions_runtime_kind"),
        table_name="mcp_runtime_sessions",
    )
    op.drop_index(
        op.f("ix_mcp_runtime_sessions_installation_id"),
        table_name="mcp_runtime_sessions",
    )
    op.drop_table("mcp_runtime_sessions")
