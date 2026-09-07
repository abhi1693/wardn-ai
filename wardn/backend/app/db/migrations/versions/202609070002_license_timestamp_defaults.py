"""Align license timestamp defaults with TimestampMixin.

Fresh PostgreSQL validation of execution evidence exposed that the original license
migration omitted the defaults used by get_or_create_installation's INSERT.

Revision ID: 202609070002
Revises: 202609070001
"""

import sqlalchemy as sa
from alembic import op

revision = "202609070002"
down_revision = "202609070001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in ("created_at", "updated_at"):
        op.alter_column("license_installations", column, server_default=sa.func.now())


def downgrade() -> None:
    for column in ("created_at", "updated_at"):
        op.alter_column("license_installations", column, server_default=None)
