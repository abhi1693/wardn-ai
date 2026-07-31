"""add agent chat tool round limit

Revision ID: 202608010001
Revises: 202607310002
Create Date: 2026-08-01
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608010001"
down_revision: str | None = "202607310002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LIMIT_KEY = "agent_chat.max_tool_rounds.per_run"
DEFAULT_VALUE = 100


def upgrade() -> None:
    connection = op.get_bind()
    workspace_ids = [
        row.id for row in connection.execute(sa.text("select id from workspaces")).fetchall()
    ]
    if not workspace_ids:
        return

    resource_limits = sa.table(
        "resource_limits",
        sa.column("id", sa.Uuid()),
        sa.column("scope_type", sa.String()),
        sa.column("scope_id", sa.Uuid()),
        sa.column("limit_key", sa.String()),
        sa.column("value", sa.Integer()),
    )
    op.bulk_insert(
        resource_limits,
        [
            {
                "id": uuid.uuid4(),
                "scope_type": "workspace",
                "scope_id": workspace_id,
                "limit_key": LIMIT_KEY,
                "value": DEFAULT_VALUE,
            }
            for workspace_id in workspace_ids
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "delete from resource_limits "
            "where scope_type = 'workspace' and limit_key = :limit_key and value = :value"
        ).bindparams(limit_key=LIMIT_KEY, value=DEFAULT_VALUE)
    )
