"""add independent MCP job cleanup retries

Revision ID: 202607160002
Revises: 202607160001
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202607160002"
down_revision: str | None = "202607160001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_operation_jobs",
        sa.Column("cleanup_max_attempts", sa.Integer(), server_default="5", nullable=False),
    )
    op.add_column(
        "mcp_operation_jobs",
        sa.Column("cleanup_available_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "mcp_operation_jobs",
        sa.Column("cleanup_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "mcp_operation_jobs",
        sa.Column("cleanup_worker_id", sa.String(length=255), server_default="", nullable=False),
    )
    op.create_index(
        op.f("ix_mcp_operation_jobs_cleanup_available_at"),
        "mcp_operation_jobs",
        ["cleanup_available_at"],
    )
    op.create_index(
        op.f("ix_mcp_operation_jobs_cleanup_lease_expires_at"),
        "mcp_operation_jobs",
        ["cleanup_lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_mcp_operation_jobs_cleanup_lease_expires_at"),
        table_name="mcp_operation_jobs",
    )
    op.drop_index(
        op.f("ix_mcp_operation_jobs_cleanup_available_at"),
        table_name="mcp_operation_jobs",
    )
    op.drop_column("mcp_operation_jobs", "cleanup_worker_id")
    op.drop_column("mcp_operation_jobs", "cleanup_lease_expires_at")
    op.drop_column("mcp_operation_jobs", "cleanup_available_at")
    op.drop_column("mcp_operation_jobs", "cleanup_max_attempts")
