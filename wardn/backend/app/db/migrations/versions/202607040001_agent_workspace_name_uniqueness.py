"""make agent names unique per workspace

Revision ID: 202607040001
Revises: 202606290005
Create Date: 2026-07-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202607040001"
down_revision: str | None = "202606290005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_agents_org_name", "agents", type_="unique")
    op.create_index(
        "uq_agents_org_name",
        "agents",
        ["organization_id", "name"],
        unique=True,
        postgresql_where=sa.text("workspace_id is null"),
    )
    op.create_index(
        "uq_agents_workspace_name",
        "agents",
        ["organization_id", "workspace_id", "name"],
        unique=True,
        postgresql_where=sa.text("workspace_id is not null"),
    )


def downgrade() -> None:
    op.drop_index("uq_agents_workspace_name", table_name="agents")
    op.drop_index("uq_agents_org_name", table_name="agents")
    op.create_unique_constraint(
        "uq_agents_org_name",
        "agents",
        ["organization_id", "name"],
    )
