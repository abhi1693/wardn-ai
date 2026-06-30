"""drop secret store default flag

Revision ID: 202606290004
Revises: 202606290003
Create Date: 2026-06-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202606290004"
down_revision: str | None = "202606290003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("uq_secret_stores_workspace_default", table_name="secret_stores")
    op.drop_index("uq_secret_stores_org_default", table_name="secret_stores")
    op.drop_index(op.f("ix_secret_stores_is_default"), table_name="secret_stores")
    op.drop_column("secret_stores", "is_default")


def downgrade() -> None:
    op.add_column(
        "secret_stores",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("secret_stores", "is_default", server_default=None)
    op.create_index(
        op.f("ix_secret_stores_is_default"),
        "secret_stores",
        ["is_default"],
        unique=False,
    )
    op.create_index(
        "uq_secret_stores_org_default",
        "secret_stores",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text("workspace_id is null and is_default is true"),
    )
    op.create_index(
        "uq_secret_stores_workspace_default",
        "secret_stores",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("workspace_id is not null and is_default is true"),
    )
