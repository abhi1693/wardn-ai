"""Add bounded runtime job diagnostics.

Revision ID: 202609080002
Revises: 202609080001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "202609080002"
down_revision = "202609080001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_job_logs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("job_kind", sa.String(32), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry", postgresql.JSONB(), nullable=False),
    )
    op.create_index(
        "ix_runtime_job_logs_scope",
        "runtime_job_logs",
        ["organization_id", "job_kind", "job_id", "id"],
    )
    op.create_index("ix_runtime_job_logs_expiry", "runtime_job_logs", ["expires_at"])


def downgrade() -> None:
    op.drop_table("runtime_job_logs")
