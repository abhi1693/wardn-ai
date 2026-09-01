"""Add signed license installation state.

Revision ID: 202609020001
Revises: 202608120001
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202609020001"
down_revision: str | None = "202608120001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "license_installations",
        sa.Column("singleton_key", sa.String(length=16), nullable=False),
        sa.Column("instance_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("signed_lease", sa.Text(), server_default="", nullable=False),
        sa.Column("renewal_token", sa.Text(), server_default="", nullable=False),
        sa.Column("lease_imported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("singleton_key"),
        sa.UniqueConstraint("instance_id"),
    )
    op.alter_column("license_installations", "signed_lease", server_default=None)
    op.alter_column("license_installations", "renewal_token", server_default=None)


def downgrade() -> None:
    op.drop_table("license_installations")
