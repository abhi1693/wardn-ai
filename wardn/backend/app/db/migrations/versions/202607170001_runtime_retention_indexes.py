"""Add leading indexes for bounded runtime retention cleanup.

Revision ID: 202607170001
Revises: 202607160008
Create Date: 2026-07-17 00:01:00.000000
"""

from alembic import op

revision: str = "202607170001"
down_revision: str | None = "202607160008"
branch_labels: str | None = None
depends_on: str | None = None

RETENTION_INDEXES = (
    (
        "ix_mcp_runtime_events_retention",
        "mcp_runtime_events",
        ["created_at", "id"],
    ),
    (
        "ix_mcp_tool_invocations_retention",
        "mcp_tool_invocations",
        ["started_at", "id"],
    ),
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for index_name, table_name, columns in RETENTION_INDEXES:
            op.create_index(
                index_name,
                table_name,
                columns,
                unique=False,
                postgresql_concurrently=True,
            )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for index_name, table_name, _columns in reversed(RETENTION_INDEXES):
            op.drop_index(
                index_name,
                table_name=table_name,
                postgresql_concurrently=True,
            )
