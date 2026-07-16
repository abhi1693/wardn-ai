"""Add time-window indexes for usage summaries.

Revision ID: 202607160005
Revises: 202607160004
Create Date: 2026-07-16 00:05:00.000000
"""

from alembic import op

revision: str = "202607160005"
down_revision: str | None = "202607160004"
branch_labels: str | None = None
depends_on: str | None = None


USAGE_SUMMARY_INDEXES = (
    ("ix_llm_usage_records_org_started", "llm_usage_records", ["organization_id", "started_at"]),
    (
        "ix_llm_usage_records_workspace_started",
        "llm_usage_records",
        ["workspace_id", "started_at"],
    ),
    ("ix_llm_usage_records_user_started", "llm_usage_records", ["user_id", "started_at"]),
    (
        "ix_mcp_tool_invocations_org_started",
        "mcp_tool_invocations",
        ["organization_id", "started_at"],
    ),
    (
        "ix_mcp_tool_invocations_workspace_started",
        "mcp_tool_invocations",
        ["workspace_id", "started_at"],
    ),
    (
        "ix_mcp_tool_invocations_user_started",
        "mcp_tool_invocations",
        ["user_id", "started_at"],
    ),
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for index_name, table_name, columns in USAGE_SUMMARY_INDEXES:
            op.create_index(
                index_name,
                table_name,
                columns,
                unique=False,
                postgresql_concurrently=True,
            )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for index_name, table_name, _columns in reversed(USAGE_SUMMARY_INDEXES):
            op.drop_index(
                index_name,
                table_name=table_name,
                postgresql_concurrently=True,
            )
