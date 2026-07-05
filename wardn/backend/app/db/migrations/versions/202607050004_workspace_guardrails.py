"""make guardrails workspace scoped

Revision ID: 202607050004
Revises: 202607050003
Create Date: 2026-07-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202607050004"
down_revision: str | None = "202607050003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("uq_guardrail_policies_org_name", table_name="guardrail_policies")
    op.drop_index("uq_guardrail_policies_workspace_name", table_name="guardrail_policies")
    op.execute("delete from guardrail_policies where workspace_id is null")
    op.alter_column("guardrail_policies", "workspace_id", nullable=False)
    op.create_index(
        "uq_guardrail_policies_workspace_name",
        "guardrail_policies",
        ["organization_id", "workspace_id", "name"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_guardrail_policies_workspace_name", table_name="guardrail_policies")
    op.alter_column("guardrail_policies", "workspace_id", nullable=True)
    op.create_index(
        "uq_guardrail_policies_workspace_name",
        "guardrail_policies",
        ["organization_id", "workspace_id", "name"],
        unique=True,
        postgresql_where=sa.text("workspace_id is not null"),
    )
    op.create_index(
        "uq_guardrail_policies_org_name",
        "guardrail_policies",
        ["organization_id", "name"],
        unique=True,
        postgresql_where=sa.text("workspace_id is null"),
    )
