"""add durable MCP operation jobs

Revision ID: 202607160001
Revises: 202607090004
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607160001"
down_revision: str | None = "202607090004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_operation_jobs",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("requested_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("operation", sa.String(length=50), nullable=False),
        sa.Column("resource_key", sa.String(length=512), nullable=False),
        sa.Column("deduplication_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="queued", nullable=False),
        sa.Column(
            "request_payload",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "result",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("progress_current", sa.Integer(), server_default="0", nullable=False),
        sa.Column("progress_total", sa.Integer(), server_default="1", nullable=False),
        sa.Column("progress_message", sa.Text(), server_default="Queued", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.String(length=255), server_default="", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=100), server_default="", nullable=False),
        sa.Column("error_message", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "cleanup_status",
            sa.String(length=32),
            server_default="not_required",
            nullable=False,
        ),
        sa.Column(
            "cleanup_payload",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("cleanup_attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cleanup_error", sa.Text(), server_default="", nullable=False),
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
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_mcp_operation_jobs_active_dedupe",
        "mcp_operation_jobs",
        ["deduplication_key"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.create_index(
        "ix_mcp_operation_jobs_claimable",
        "mcp_operation_jobs",
        ["status", "available_at", "created_at"],
    )
    for column in (
        "organization_id",
        "workspace_id",
        "requested_by_id",
        "operation",
        "resource_key",
        "status",
        "available_at",
        "lease_expires_at",
        "cleanup_status",
    ):
        op.create_index(op.f(f"ix_mcp_operation_jobs_{column}"), "mcp_operation_jobs", [column])

    op.create_table(
        "mcp_operation_job_events",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("level", sa.String(length=20), server_default="info", nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("progress_current", sa.Integer(), nullable=True),
        sa.Column("progress_total", sa.Integer(), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["job_id"], ["mcp_operation_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_mcp_operation_job_events_job_id"),
        "mcp_operation_job_events",
        ["job_id"],
    )
    op.create_index(
        op.f("ix_mcp_operation_job_events_event_type"),
        "mcp_operation_job_events",
        ["event_type"],
    )
    op.create_index(
        op.f("ix_mcp_operation_job_events_created_at"),
        "mcp_operation_job_events",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_mcp_operation_job_events_created_at"),
        table_name="mcp_operation_job_events",
    )
    op.drop_index(
        op.f("ix_mcp_operation_job_events_event_type"),
        table_name="mcp_operation_job_events",
    )
    op.drop_index(
        op.f("ix_mcp_operation_job_events_job_id"),
        table_name="mcp_operation_job_events",
    )
    op.drop_table("mcp_operation_job_events")

    for column in reversed(
        (
            "organization_id",
            "workspace_id",
            "requested_by_id",
            "operation",
            "resource_key",
            "status",
            "available_at",
            "lease_expires_at",
            "cleanup_status",
        )
    ):
        op.drop_index(op.f(f"ix_mcp_operation_jobs_{column}"), table_name="mcp_operation_jobs")
    op.drop_index("ix_mcp_operation_jobs_claimable", table_name="mcp_operation_jobs")
    op.drop_index("uq_mcp_operation_jobs_active_dedupe", table_name="mcp_operation_jobs")
    op.drop_table("mcp_operation_jobs")
