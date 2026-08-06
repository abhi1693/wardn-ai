"""Add durable agent run resume jobs.

Revision ID: 202608060003
Revises: 202608060002
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202608060003"
down_revision: str | None = "202608060002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_run_resume_jobs",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("approval_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=255), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
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
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_agent_run_resume_jobs_status",
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["approval_id"],
            ["agent_tool_approvals.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_agent_run_resume_jobs_agent_id"),
        "agent_run_resume_jobs",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_run_resume_jobs_agent_run_id"),
        "agent_run_resume_jobs",
        ["agent_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_run_resume_jobs_approval_id"),
        "agent_run_resume_jobs",
        ["approval_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_run_resume_jobs_claimable",
        "agent_run_resume_jobs",
        ["status", "available_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_run_resume_jobs_lease_expires_at"),
        "agent_run_resume_jobs",
        ["lease_expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_run_resume_jobs_organization_id"),
        "agent_run_resume_jobs",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_run_resume_jobs_status"),
        "agent_run_resume_jobs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "uq_agent_run_resume_jobs_active_approval",
        "agent_run_resume_jobs",
        ["approval_id"],
        unique=True,
        postgresql_where=sa.text("status in ('queued', 'running')"),
    )
    op.create_index(
        op.f("ix_agent_run_resume_jobs_user_id"),
        "agent_run_resume_jobs",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_run_resume_jobs_workspace_id"),
        "agent_run_resume_jobs",
        ["workspace_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_agent_run_resume_jobs_workspace_id"), table_name="agent_run_resume_jobs")
    op.drop_index(op.f("ix_agent_run_resume_jobs_user_id"), table_name="agent_run_resume_jobs")
    op.drop_index("uq_agent_run_resume_jobs_active_approval", table_name="agent_run_resume_jobs")
    op.drop_index(op.f("ix_agent_run_resume_jobs_status"), table_name="agent_run_resume_jobs")
    op.drop_index(
        op.f("ix_agent_run_resume_jobs_organization_id"),
        table_name="agent_run_resume_jobs",
    )
    op.drop_index(
        op.f("ix_agent_run_resume_jobs_lease_expires_at"),
        table_name="agent_run_resume_jobs",
    )
    op.drop_index("ix_agent_run_resume_jobs_claimable", table_name="agent_run_resume_jobs")
    op.drop_index(op.f("ix_agent_run_resume_jobs_approval_id"), table_name="agent_run_resume_jobs")
    op.drop_index(
        op.f("ix_agent_run_resume_jobs_agent_run_id"),
        table_name="agent_run_resume_jobs",
    )
    op.drop_index(op.f("ix_agent_run_resume_jobs_agent_id"), table_name="agent_run_resume_jobs")
    op.drop_table("agent_run_resume_jobs")
